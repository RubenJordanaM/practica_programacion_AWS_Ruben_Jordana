# lambdas/notify_low_stock/lambda_function.py
import os
import boto3
import json
import logging
from decimal import Decimal

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sns = boto3.client('sns')
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')
LOW_STOCK_THRESHOLD = 5 # Definimos "bajo stock" como < 5

def lambda_handler(event, context):
    """
    Handler principal de la Lambda.
    Se dispara por un Stream de DynamoDB.
    """
    logger.info("Evento de DynamoDB Stream recibido: %s", json.dumps(event))
    
    if not SNS_TOPIC_ARN:
        logger.error("La variable de entorno SNS_TOPIC_ARN no está definida.")
        return

    notifications_sent = 0
    
    for record in event.get('Records', []):
        # Nos interesan eventos de inserción (INSERT) o modificación (MODIFY)
        if record.get('eventName') not in ['INSERT', 'MODIFY']:
            continue
            
        # El 'NewImage' contiene los datos del item *después* del cambio
        new_image = record.get('dynamodb', {}).get('NewImage')
        
        if not new_image:
            logger.warning("Registro sin NewImage, saltando...")
            continue
            
        try:
            # Los datos del stream vienen en formato DynamoDB JSON
            store = new_image.get('Store', {}).get('S')
            item = new_image.get('Item', {}).get('S')
            # 'N' significa que es un número (viene como string)
            count = Decimal(new_image.get('Count', {}).get('N', '0'))
            
            if store and item and count < LOW_STOCK_THRESHOLD:
                subject = f"Alerta de Bajo Stock: {item} en {store}"
                message = (
                    f"¡Atención! El inventario está bajo para el artículo:\n\n"
                    f"Tienda: {store}\n"
                    f"Artículo: {item}\n"
                    f"Cantidad restante: {count}\n\n"
                    f"Por favor, reabastecer."
                )
                
                # Publicar en SNS
                sns.publish(
                    TopicArn=SNS_TOPIC_ARN,
                    Message=message,
                    Subject=subject
                )
                logger.info("Notificación de bajo stock enviada para %s en %s", item, store)
                notifications_sent += 1
                
        except Exception as e:
            logger.error(
                "Error al procesar el registro del stream: %s. Registro: %s",
                e, 
                record
            )
            
    return {
        'statusCode': 200,
        'body': f'Notificaciones enviadas: {notifications_sent}'
    }