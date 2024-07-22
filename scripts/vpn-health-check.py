# example cron entry
#  */15 * * * * /usr/bin/python3 /path/to/health-check.py

from time import sleep
from docker import APIClient
from docker.models.containers import Container
import docker
import json
import requests as req
import logging
import logging_loki
import xml.etree.ElementTree as ET 

logging_loki.emitter.LokiEmitter.level_tag="level"

def parseConfig():
    config = None
    with open("config.json") as config_file:
        config_data = json.load(config_file)
        config = config_data
    return config

def setupLogger(loki_endpoint):
    handler = logging_loki.LokiHandler(url=loki_endpoint,version="1", tags={"service": "vpn-health-check"})
    logger = logging.getLogger('health-check-logger')
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    return logger, handler

def getKeyFromXML(path):
    tree = ET.parse(path)
    root = tree.getroot()
    for child in root:
        if child.tag == "ApiKey":
            return child.text
    return None

def get_health(container: Container):
    api_client = APIClient()
    inspect_results = api_client.inspect_container(container.name)
    return inspect_results['State']['Health']['Status']

def main():

    config = parseConfig()
    logger, handler = setupLogger(config['loki_endpoint'])

    # get all api keys from service configs
    prowlarr_api_key = getKeyFromXML(config['base_path'] + config['prowlarr']['config_path']) 
    sonarr_api_key = getKeyFromXML(config['base_path'] + config['sonarr']['config_path'])
    radarr_api_key = getKeyFromXML(config['base_path'] + config['radarr']['config_path'])   
    # grab service urls from config
    prowlarr_url = config['prowlarr']['url']
    sonarr_url = config['sonarr']['url']
    radarr_url = config['radarr']['url']

    # connect to docker socket & grab containers
    client = docker.from_env()
    vpn = client.containers.get("vpn")
    transmission = client.containers.get("transmission")
    prowlarr = client.containers.get("prowlarr")

    if get_health(vpn) == "healthy":
        logger.info("vpn healthly no restart required")
        return

    loki_push("vpn unhealthy...restarting", "error")
    transmission.stop()
    prowlarr.stop()

    vpn.restart()

    while( get_health(vpn) != "healthy"): 
        sleep(1)
    
    transmission.start()
    prowlarr.start()
    sleep(60) # await vpn startup

    # download client test connection
    req.post(f"{prowlarr_url}/api/v1/downloadclient/testall?apikey={prowlarr_api_key}")
    req.post(f"{sonarr_url}/api/v3/downloadclient/testall?apikey={sonarr_api_key}")
    req.post(f"{radarr_url}/api/v3/downloadclient/testall?apikey={radarr_api_key}")
    # indexer test connnection
    req.post(f"{prowlarr_url}/api/v1/indexer/testall?apikey={prowlarr_api_key}")
    req.post(f"{sonarr_url}/api/v3/indexer/testall?apikey={sonarr_api_key}")
    req.post(f"{radarr_url}/api/v3/indexer/testall?apikey={radarr_api_key}")
    # report success to loki
    logger.warning("successfully restarted vpn", "info")


if __name__ == "__main__":
    main()


