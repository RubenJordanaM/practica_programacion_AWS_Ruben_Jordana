# infra/teardown.py
import boto3
import os
import logging
import sys
from dotenv import load_dotenv

# --- Configuración de Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Cargar Variables de Entorno ---
load_dotenv()
try:
    PREFIX = os.environ['UNIQUE_PREFIX']
    REGION = os.environ['AWS_REGION']
    ACCOUNT_ID = os.environ['AWS_ACCOUNT_ID']
except KeyError as e:
    logger.error(f"Error: La variable de entorno {e} no está definida en el archivo .env")
    sys.exit(1)

# --- Nombres de Recursos (deben coincidir con deploy.py) ---
BUCKET_UPLOADS = f'{PREFIX}-inventory-uploads'
BUCKET_WEB = f'{PREFIX}-inventory-web'
DYNAMO_TABLE = f'{PREFIX}-Inventory'
SNS_TOPIC = f'{PREFIX}-NoStock'
API_NAME = f'{PREFIX}-InventoryAPI'

LAMBDA_ROLE_LOADER = f'{PREFIX}-Lambda-Loader-Role'
LAMBDA_ROLE_API = f'{PREFIX}-Lambda-API-Role'
LAMBDA_ROLE_NOTIFY = f'{PREFIX}-Lambda-Notify-Role'

LAMBDA_FUNC_LOAD = f'{PREFIX}-load_inventory'
LAMBDA_FUNC_API = f'{PREFIX}-get_inventory_api'
LAMBDA_FUNC_NOTIFY = f'{PREFIX}-notify_low_stock'

# --- Inicializar Clientes de Boto3 ---
iam_client = boto3.client('iam', region_name=REGION)
lambda_client = boto3.client('lambda', region_name=REGION)
s3_client = boto3.client('s3', region_name=REGION)
dynamodb_client = boto3.client('dynamodb', region_name=REGION)
sns_client = boto3.client('sns', region_name=REGION)
apigw_client = boto3.client('apigatewayv2', region_name=REGION)
s3_resource = boto3.resource('s3', region_name=REGION)

# --- Helper para ignorar "No Encontrado" ---
def safe_delete(delete_function, resource_name, **kwargs):
    """Ejecuta una función de borrado y suprime errores 'NotFound'."""
    try:
        delete_function(**kwargs)
        logger.info(f"Borrado exitoso: {resource_name}")
    except Exception as e:
        # Errores comunes de "No encontrado"
        if "NoSuchEntity" in str(e) or \
           "ResourceNotFoundException" in str(e) or \
           "NotFoundException" in str(e) or \
           "NoSuchBucket" in str(e) or \
           "InvalidIntegration" in str(e):
            logger.warning(f"Recurso ya borrado: {resource_name}")
        else:
            logger.error(f"Error al borrar {resource_name}: {e}")

# --- 1. Vaciar y Borrar Buckets S3 ---
def delete_s3_buckets():
    logger.info("--- 1. Borrando Buckets S3 ---")
    
    def empty_and_delete(bucket_name):
        try:
            logger.info(f"Vaciando bucket {bucket_name}...")
            bucket = s3_resource.Bucket(bucket_name)
            # Borra todas las versiones de objetos (si estuviera habilitado)
            bucket.object_versions.delete()
            # Borra todos los objetos
            bucket.objects.all().delete()
            logger.info(f"Bucket {bucket_name} vaciado.")
            
            # Borrar el bucket
            safe_delete(
                s3_client.delete_bucket,
                bucket_name,
                Bucket=bucket_name
            )
        except s3_client.exceptions.NoSuchBucket:
             logger.warning(f"Recurso ya borrado: {bucket_name}")
        except Exception as e:
            logger.error(f"Error vaciando/borrando {bucket_name}: {e}")

    empty_and_delete(BUCKET_UPLOADS)
    empty_and_delete(BUCKET_WEB)

# --- 2. Borrar API Gateway ---
def delete_api_gateway():
    logger.info("--- 2. Borrando API Gateway ---")
    try:
        apis = apigw_client.get_apis()['Items']
        api = next((a for a in apis if a['Name'] == API_NAME), None)
        
        if api:
            api_id = api['ApiId']
            safe_delete(
                apigw_client.delete_api,
                f"API Gateway {API_NAME}",
                ApiId=api_id
            )
        else:
            logger.warning(f"No se encontró la API Gateway: {API_NAME}")
    except Exception as e:
        logger.error(f"Error buscando API Gateway: {e}")

# --- 3. Borrar Funciones Lambda y Mapeos ---
def delete_lambda_functions():
    logger.info("--- 3. Borrando Funciones Lambda ---")
    
    # 3a. Borrar Mapeo de DDB Stream
    try:
        mappings = lambda_client.list_event_source_mappings(
            FunctionName=LAMBDA_FUNC_NOTIFY
        )['EventSourceMappings']
        for m in mappings:
            safe_delete(
                lambda_client.delete_event_source_mapping,
                f"Event Source Mapping {m['UUID']}",
                UUID=m['UUID']
            )
    except Exception as e:
         logger.warning(f"No se pudo borrar el mapping para {LAMBDA_FUNC_NOTIFY} (puede que ya no exista): {e}")

    # 3b. Borrar las funciones
    for func_name in [LAMBDA_FUNC_LOAD, LAMBDA_FUNC_API, LAMBDA_FUNC_NOTIFY]:
        safe_delete(
            lambda_client.delete_function,
            f"Lambda {func_name}",
            FunctionName=func_name
        )
        
# --- 4. Borrar Tópico SNS ---
def delete_sns_topic():
    logger.info("--- 4. Borrando Tópico SNS ---")
    topic_arn = f"arn:aws:sns:{REGION}:{ACCOUNT_ID}:{SNS_TOPIC}"
    safe_delete(
        sns_client.delete_topic,
        f"SNS Topic {SNS_TOPIC}",
        TopicArn=topic_arn
    )

# --- 5. Borrar Tabla DynamoDB ---
def delete_dynamodb_table():
    logger.info("--- 5. Borrando Tabla DynamoDB ---")
    safe_delete(
        dynamodb_client.delete_table,
        f"DynamoDB Table {DYNAMO_TABLE}",
        TableName=DYNAMO_TABLE
    )

# --- Función Principal (main) ---
def main():
    logger.info(f"--- INICIANDO TEARDOWN para {PREFIX} en {REGION} ---")
    logger.warning("¡Esto es destructivo y borrará todos los recursos creados!")
    
    # Pedir confirmación
    confirm = input(f"Escribe '{PREFIX}' para confirmar el borrado: ")
    if confirm != PREFIX:
        logger.info("Confirmación incorrecta. Abortando teardown.")
        sys.exit(0)
        
    logger.info("Confirmación aceptada. Procediendo con el borrado...")
    
    # El orden de borrado es importante (inverso a la creación)
    
    # 1. Borrar S3 (contienen notificaciones) y API GW (usa lambdas)
    delete_api_gateway()
    delete_s3_buckets() # Vacía y borra
    
    # 2. Borrar Lambdas y triggers
    delete_lambda_functions() # Incluye el trigger de DDB
    
    # 3. Borrar SNS y DDB
    delete_sns_topic()
    delete_dynamodb_table()

    # 4. Limpiar archivos locales
    try:
        os.remove('deployment-outputs.json')
        logger.info("Archivo 'deployment-outputs.json' limpiado.")
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.error(f"No se pudo limpiar 'deployment-outputs.json': {e}")
        
    logger.info("--- TEARDOWN COMPLETADO ---")

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    main()