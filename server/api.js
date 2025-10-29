// Agent léger Node.js : collecte métriques et POST JSON vers API distante.
//
// POUR EXÉCUTER CE SCRIPT :
// 1. Assurez-vous d'avoir Node.js installé.
// 2. Installez le package 'js-yaml' (requis pour la configuration YAML) :
//    npm install js-yaml
// 3. Créez un fichier de configuration à /etc/sylon/config.yaml
// 4. Exécutez : node sylon-agent.js
//
// NOTE: La métrique 'cpu_percent' est simplifiée en Node.js car le module 'os'
// ne fournit pas de pourcentage instantané comme 'psutil'; elle est calculée
// en surveillant les ticks CPU sur un intervalle.
//
const os = require('os');
const fs = require('fs');
const path = require('path');
const https = require('https');
const crypto = require('crypto');
const url = require('url');
const jsyaml = require('js-yaml'); // External dependency for YAML

// --- Configuration par Défaut ---
const DEFAULT_CONFIG = {
    endpoint: "NULL",
    api_key: "NULL",
    interval_seconds: 300,
    timeout_seconds: 10,
    max_retries: 5,
    backoff_base: 2,
    jitter: 0.3
};

const LOG_PREFIX = "[sylon-agent]";

function log(level, message, ...args) {
    const timestamp = new Date().toISOString();
    const formattedMessage = message.replace(/%s/g, () => args.shift());
    console.log(`${timestamp} ${level} ${LOG_PREFIX} ${formattedMessage}`);
}

// --- Chargement de la Configuration ---

function loadConfig(configPath = "/etc/sylon/config.yaml") {
    let config = { ...DEFAULT_CONFIG };
    try {
        if (fs.existsSync(configPath)) {
            const fileContents = fs.readFileSync(configPath, 'utf8');
            const cfgFromFile = jsyaml.load(fileContents);
            if (cfgFromFile) {
                Object.assign(config, cfgFromFile);
                log("INFO", "Configuration chargée depuis %s.", configPath);
            }
        } else {
            log("WARN", "Fichier de configuration non trouvé (%s), utilisation des valeurs par défaut.", configPath);
        }
    } catch (e) {
        log("ERROR", "Erreur lors du chargement ou de l'analyse du fichier de configuration : %s", e.message);
    }
    return config;
}

// --- Obtention de l'ID Machine ---

function getMachineId() {
    // 1. Essayer les emplacements standard de systemd/dbus
    const paths = ["/etc/machine-id", "/var/lib/dbus/machine-id"];
    for (const p of paths) {
        try {
            if (fs.existsSync(p)) {
                return fs.readFileSync(p, 'utf8').trim();
            }
        } catch (e) {
            // Ignorer, essayer le chemin suivant
        }
    }

    // 2. Repli sur l'UUID généré et persistant
    const persistencePath = "/var/lib/sylon/id";
    try {
        // Tente de lire l'ID existant
        if (fs.existsSync(persistencePath)) {
            return fs.readFileSync(persistencePath, 'utf8').trim();
        }

        // Génère et enregistre un nouvel UUID
        const mid = crypto.randomUUID();
        const dir = path.dirname(persistencePath);

        // Assure que le répertoire existe (synchrone pour éviter les problèmes de course)
        if (!fs.existsSync(dir)) {
            fs.mkdirSync(dir, { recursive: true });
        }
        fs.writeFileSync(persistencePath, mid, 'utf8');
        return mid;

    } catch (e) {
        log("ERROR", "Impossible de lire/écrire l'ID machine persistant: %s", e.message);
        // 3. Repli ultime sur un UUID aléatoire à chaque exécution (moins stable)
        return crypto.randomUUID();
    }
}

// --- Métriques CPU et Disque (Substituts de psutil) ---

// Placeholder pour stocker l'état précédent des CPU
let previousCpuTicks = null;

function calculateCpuPercent() {
    const cpus = os.cpus();
    let totalIdle = 0;
    let totalTick = 0;

    const currentCpuTicks = cpus.map(cpu => {
        const times = cpu.times;
        const currentTick = times.user + times.nice + times.sys + times.idle + times.irq;
        totalIdle += times.idle;
        totalTick += currentTick;
        return { idle: times.idle, total: currentTick };
    });

    if (previousCpuTicks === null) {
        previousCpuTicks = currentCpuTicks;
        // La première fois, nous n'avons pas de pourcentage précis, retournons une valeur arbitraire ou attendons.
        return 0;
    }

    let idleDifference = 0;
    let totalDifference = 0;

    for (let i = 0; i < cpus.length; i++) {
        idleDifference += currentCpuTicks[i].idle - previousCpuTicks[i].idle;
        totalDifference += currentCpuTicks[i].total - previousCpuTicks[i].total;
    }

    previousCpuTicks = currentCpuTicks;

    if (totalDifference > 0) {
        const idlePercent = idleDifference / totalDifference;
        // Retourne le pourcentage d'utilisation (100 - % inactif)
        return parseFloat((100 - idlePercent * 100).toFixed(1));
    }

    return 0; // Aucune différence mesurée (si les cpus sont à l'arrêt)
}

function getDiskUsage() {
    // Le module 'os' de Node.js n'a pas de fonction intégrée pour l'utilisation du disque.
    // Dans un environnement de production Node.js, une bibliothèque comme 'check-disk-space'
    // ou 'node-diskinfo' serait utilisée, ou un appel système.
    // Ici, nous fournissons des valeurs factices pour garantir la structure de la charge utile.
    log("WARN", "Les métriques de disque (total, utilisé, libre) sont simulées. Un package externe est requis pour les valeurs réelles.");
    return {
        total: 100000000000, // 100 GB (Simulé)
        used: 40000000000,   // 40 GB (Simulé)
        free: 60000000000,   // 60 GB (Simulé)
        percent: 40.0        // 40% (Simulé)
    };
}

// --- Collecte de Métriques ---

function collectMetrics() {
    const data = {};
    data.timestamp = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'); // Format ISO 8601 UTC + 'Z'
    data.hostname = os.hostname();
    data.machine_id = getMachineId();

    const platform = os.platform();
    data.platform = {
        system: os.type(), // e.g., 'Linux', 'Darwin'
        release: os.release(),
        version: os.version()
    };

    // CPU
    data.cpu_percent = calculateCpuPercent();
    data.cpu_count_logical = os.cpus().length;
    // La détermination du count physique est complexe sans psutil, nous laissons la logique=false
    // mais dans Node.js, c'est généralement le même que le logique sans bibliothèque supplémentaire
    data.cpu_count_physical = os.cpus().length;

    // Mémoire
    const totalMem = os.totalmem();
    const freeMem = os.freemem();
    const usedMem = totalMem - freeMem;
    const memPercent = parseFloat(((usedMem / totalMem) * 100).toFixed(1));

    data.memory = {
        total: totalMem,
        available: freeMem, // 'available' en psutil est souvent plus précis, mais freeMem est le meilleur équivalent intégré
        percent: memPercent
    };

    // Disque (Simulation ou via appel système dans une vraie application)
    data.disk = getDiskUsage();

    // Load Average
    const loadavg = os.loadavg();
    data.loadavg = { "1": loadavg[0], "5": loadavg[1], "15": loadavg[2] };

    // Uptime
    data.uptime_seconds = os.uptime();

    // Réseau (Trouver la première IPv4 non-loopback)
    const interfaces = os.networkInterfaces();
    let ipv4 = null;
    for (const ifname in interfaces) {
        for (const addr of interfaces[ifname]) {
            if (addr.family === 'IPv4' && !addr.internal) {
                ipv4 = addr.address;
                break;
            }
        }
        if (ipv4) break;
    }
    data.ipv4 = ipv4;

    return data;
}

// --- Envoi de la Charge Utile (Payload) ---

async function sendPayload(cfg, payload) {
    const { endpoint, api_key, max_retries, backoff_base, jitter, timeout_seconds } = cfg;

    if (endpoint === "NULL") {
        log("ERROR", "L'endpoint de l'API n'est pas configuré. Abandon de l'envoi.");
        return false;
    }

    const { hostname, pathname } = url.parse(endpoint);
    const postData = JSON.stringify(payload);
    const headers = {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(postData),
        'Authorization': `Bearer ${api_key}`
    };

    const options = {
        hostname: hostname,
        port: 443, // Assumer HTTPS, ajuster si nécessaire
        path: pathname,
        method: 'POST',
        headers: headers,
        timeout: timeout_seconds * 1000 // Convertir en millisecondes
    };

    for (let attempt = 1; attempt <= max_retries; attempt++) {
        try {
            const result = await new Promise((resolve, reject) => {
                const req = https.request(options, (res) => {
                    let data = '';
                    res.on('data', (chunk) => { data += chunk; });
                    res.on('end', () => {
                        resolve({ statusCode: res.statusCode, body: data });
                    });
                });

                req.on('timeout', () => {
                    req.destroy(new Error('Request Timeout'));
                });

                req.on('error', (e) => {
                    reject(e);
                });

                req.write(postData);
                req.end();
            });

            const { statusCode, body } = result;

            if (statusCode >= 200 && statusCode < 300) {
                log("INFO", "Charge utile acceptée (status=%s)", statusCode);
                return true;
            } else if (statusCode >= 400 && statusCode < 500) {
                log("ERROR", "Erreur client lors de l'envoi de la charge utile: %s %s", statusCode, body);
                return false;
            } else {
                log("WARN", "Erreur serveur %s; tentative %s/%s", statusCode, attempt, max_retries);
            }
        } catch (e) {
            log("WARN", "Échec de la requête tentative %s/%s: %s", attempt, max_retries, e.message);
        }

        if (attempt < max_retries) {
            // Backoff avec jitter
            const sleepTime = (backoff_base ** attempt) + (Math.random() * jitter);
            log("INFO", "Nouvelle tentative dans %s secondes...", sleepTime.toFixed(2));
            await new Promise(resolve => setTimeout(resolve, sleepTime * 1000));
        }
    }

    log("ERROR", "Toutes les tentatives ont échoué.");
    return false;
}

// --- Boucle Principale ---

async function main() {
    const cfg = loadConfig();
    const interval = parseInt(cfg.interval_seconds, 10);

    log("INFO", "Démarrage de l'agent; envoi à %s toutes les %s secondes", cfg.endpoint, interval);

    // Exécuter la première fois immédiatement
    try {
        const payload = collectMetrics();
        await sendPayload(cfg, payload);
    } catch (e) {
        log("ERROR", "Erreur lors de la première exécution: %s", e.message);
    }

    // Boucle d'intervalle
    setInterval(async () => {
        try {
            const payload = collectMetrics();
            await sendPayload(cfg, payload);
        } catch (e) {
            log("ERROR", "Erreur inattendue dans la boucle principale: %s", e.message);
        }
    }, interval * 1000);
}

// Gestion de l'interruption
process.on('SIGINT', () => {
    log("INFO", "Arrêt de l'agent...");
    process.exit(0);
});

// Démarrer l'application
main();
