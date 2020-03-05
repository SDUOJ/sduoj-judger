import pika

connection = pika.BlockingConnection(pika.ConnectionParameters(host='123.232.223.142'))
channel = connection.channel()

channel.queue_declare(queue='hello dd', durable=True)  # durable: to set the broker durable


def callback(ch, method, properties, body):
    print(body)
    ch.basic_ack(delivery_tag=method.delivery_tag)  # manual ack


channel.basic_qos(prefetch_count=1)  # limit the number
channel.basic_consume(queue='hello dd', on_message_callback=callback)

print(' [*] Waiting for messages. To exit press CTRL+C')
channel.start_consuming()
