
Continusouly poll a Enphase Envoy control hub
- extract production and consumptionmeter readings
- extract individual panel inverters measurements
- publish to mqtt
- continuous looping (only 1 sec between passes) but with a local cache of values and only publishes modified values
- handles the authentication via token obtained from Enphase Entrez service. Getting or Refreshing a token need internet access... but using it against the Envoy does not. Owner tokens appear valid for 1 year. 

Enphase itself only appears to get meter readings every 5 minutes or so, but the productin and consumption readings seem real time.

No idea if the contant polling will break the Envoy. Do so at your own risk!!

Docker image "robinrottier/enphase-polling" in this repository:
  https://hub.docker.com/repository/docker/robinrottier/enphase-polling

Use enviroment variables to override all the key parameters for the Envoy to read from and MQTT broker to publish too

OR use a docker compose file file this to wrap them all up...
```
services:
  app:
    image: enphase-polling
    environment:
      - enphase_username=
      - enphase_password=
      - gateway_host=https://envoy
      - gateway_serial_number=123456789012
      - mqtt_broker=mqtt
      - mqtt_port=1883
      - mqtt_username=
      - mqtt_password=
```

