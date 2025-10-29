apt-get update && apt-get install -y python3-pip 
pip3 install psutil requests pyyaml    

mv agent.py /usr/local/bin/
chmod +x /usr/local/bin/agent.py

mv sylon-agent.service /etc/systemd/system/

mkdir /etc/sylon
mv config.yaml /etc/sylon/

systemctl daemon-reload
systemctl enable --now sylon-agent.service

