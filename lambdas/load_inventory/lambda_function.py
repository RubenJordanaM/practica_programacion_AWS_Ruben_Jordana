# lambdas/load_inventory/lambda_function.py
import os
import boto3
import csv
import io
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
# Obtenemos el nombre de la tabla de una variable de entorno
TABLE_NAME = os.environ.get('DYNAMO_TABLE_NAME', 'Inventory')
table = dynamodb.Table(TABLE_NAME)

def parse_csv_row(row):
    """
    Normaliza las cabeceras del CSV (Store, Item, Count)
    independientemente de mayúsculas/minúsculas o idioma.
    """
    cleaned = { (k or "").strip().lower(): v.strip() for k, v in row.items() }
    
    store = cleaned.get("store") or cleaned.get("tienda")
    item = cleaned.get("item") or cleaned.get("articulo")
    
    count_str = cleaned.get("count") or cleaned.get("cantidad") or "0"
    try:
        count = int(count_str)
    except ValueError:
        count = 0
        
    if not store or not item:
        return None
        
    return {
        "Store": store,
        "Item": item,
        "Count": count
    }

def lambda_handler(event, context):
    """
    Handler principal de la Lambda.
    """
    logger.info("Evento S3 recibido: %s", event)
    
    # 1. Obtener el bucket y la clave (nombre del archivo) del evento S3
    try:
        s3_event = event['Records'][0]['s3']
        bucket_name = s3_event['bucket']['name']
        object_key = s3_event['object']['key']
    except (KeyError, IndexError) as e:
        logger.error("Error al parsear el evento S3: %s", e)
        return {'statusCode': 400, 'body': 'Evento S3 mal formado.'}

    # 2. Leer el objeto CSV de S3
    s3_client = boto3.client('s3')
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
        csv_content = response['Body'].read().decode('utf-8')
        logger.info("CSV leído correctamente de S3.")
    except Exception as e:
        logger.error("Error al leer el objeto de S3: %s", e)
        return {'statusCode': 500, 'body': f'Error al leer {object_key} de {bucket_name}'}

    # 3. Parsear el CSV y preparar la carga a DynamoDB
    # Usamos io.StringIO para tratar el string del CSV como un archivo
    csv_file = io.StringIO(csv_content)
    reader = csv.DictReader(csv_file)
    
    items_to_put = []
    for row in reader:
        parsed_item = parse_csv_row(row)
        if parsed_item:
            items_to_put.append({
                'PutRequest': {
                    'Item': parsed_item
                }
            })

    if not items_to_put:
        logger.warning("No se encontraron items válidos en el CSV.")
        return {'statusCode': 200, 'body': 'No se encontraron items válidos.'}

    # 4. Cargar en DynamoDB usando BatchWriteItem
    # BatchWriteItem es más eficiente que PutItem en un bucle.
    # Maneja lotes de 25 items a la vez.
    try:
        with table.batch_writer() as batch:
            for i in range(0, len(items_to_put), 25):
                batch_chunk = items_to_put[i:i+25]
                for item_request in batch_chunk:
                    batch.put_item(Item=item_request['PutRequest']['Item'])
                    
        logger.info("Carga exitosa de %d items a DynamoDB.", len(items_to_put))
        return {
            'statusCode': 200,
            'body': f'Se cargaron {len(items_to_put)} items en la tabla {TABLE_NAME}'
        }
    except Exception as e:
        logger.error("Error al escribir en DynamoDB: %s", e)
        return {'statusCode': 500, 'body': f'Error al escribir en DynamoDB: {e}'}