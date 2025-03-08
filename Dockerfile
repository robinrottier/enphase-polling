FROM python:3.11-slim-bookworm
ADD requirements.txt /
RUN pip install -r requirements.txt
ADD *.py /
ADD configuration/credentials.json /configuration/

# override these when you invoke the container
ENV enphase_username=your_enphase_username
ENV enphase_password=your_enphase_password
ENV gateway_host=https://envoy
ENV gateway_serial_number=123456789012
ENV gateway_trust=true
ENV mqtt_broker=mqtt
ENV mqtt_port=1883
ENV mqtt_clientid=envoypoll
ENV mqtt_root=envoy
ENV mqtt_username=
ENV mqtt_password=

CMD [ "python", "./enphase_polling.py" ]
