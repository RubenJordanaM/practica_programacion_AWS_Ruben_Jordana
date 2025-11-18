# lambdas/get_inventory_api/lambda_function.py
import os
import json
import boto3
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
TABLE_NAME = os.environ.get('DYNAMO_TABLE_NAME', 'Inventory')
table = dynamodb.Table(TABLE_NAME)

class DecimalEncoder(json.JSONEncoder):
    """Clase helper para convertir Decimal de DynamoDB a float/int para JSON."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            if obj % 1 == 0:
                return int(obj)
            else:
                return float(obj)
        return super(DecimalEncoder, self).default(obj)

def make_response(status_code, body):
    """Crea una respuesta HTTP para API Gateway con CORS."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",  # Habilita CORS
            "Access-Control-Allow-Methods": "GET,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type"
        },
        "body": json.dumps(body, cls=DecimalEncoder)
    }

def lambda_handler(event, context):
    """
    Handler principal de la Lambda.
    Rutas:
    - GET /items        -> Escanea toda la tabla
    - GET /items/{store} -> Hace Query por 'Store'
    """
    print("Evento de API Gateway recibido:", event)
    
    # API Gateway HTTP API (payload v2.0)
    raw_path = event.get('rawPath', '/')
    path_parameters = event.get('pathParameters', {})
    store = path_parameters.get('store')

    try:
        if raw_path == '/items' and not store:
            # Ruta: GET /items
            # Escanea toda la tabla (Scan).
            # Nota: Scan es ineficiente para tablas grandes.
            # Para esta práctica es aceptable.
            response = table.scan()
            items = response.get('Items', [])
            
            # Manejar paginación si la tabla es grande
            while 'LastEvaluatedKey' in response:
                response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
                items.extend(response.get('Items', []))
                
            return make_response(200, items)

        elif store:
            # Ruta: GET /items/{store}
            # Usa Query (eficiente) para buscar por la Partition Key (Store).
            response = table.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key('Store').eq(store)
            )
            items = response.get('Items', [])
            return make_response(200, items)

        else:
            return make_response(404, {"error": "Ruta no encontrada"})

    except Exception as e:
        print(f"Error al consultar DynamoDB: {e}")
        return make_response(500, {"error": f"Error interno del servidor: {str(e)}"})