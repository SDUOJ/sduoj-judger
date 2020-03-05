import pika
import json

fo = open("../file/E.cc", "r+")

str = fo.read()

stt = {"Language": "C++", "Code": str}

str = json.dumps(stt)

connection = pika.BlockingConnection(pika.ConnectionParameters('123.232.223.142'))
# connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))

channel = connection.channel()

channel.queue_declare(queue='hello hrz', durable=True) # durable: to set the broker durable

for i in range(5):
    channel.basic_publish(exchange='',
                          routing_key='hello hrz',
                          body=str,
                          properties=pika.BasicProperties(
                              delivery_mode=2,  # make message persistent
                          ))

print(" [x] Sent 'Hello World!'")

connection.close()
