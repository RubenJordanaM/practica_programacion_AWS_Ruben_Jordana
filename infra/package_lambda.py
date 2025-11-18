# infra/package_lambda.py
import os
import zipfile
import logging

# Configuración básica de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def package_lambda_function(source_dir, zip_name):
    """
    Crea un archivo .zip a partir de un directorio de código fuente de Lambda.
    
    :param source_dir: Directorio que contiene lambda_function.py
    :param zip_name: Ruta completa del archivo .zip de salida (ej: build/load_inventory.zip)
    """
    
    # Asegurarse de que el directorio de salida (ej: 'build/') exista
    output_dir = os.path.dirname(zip_name)
    if output_dir and not os.path.exists(output_dir):
        logger.info(f"Creando directorio de salida: {output_dir}")
        os.makedirs(output_dir)

    logger.info(f"Empaquetando {source_dir} en {zip_name}...")
    
    try:
        with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Añadir el archivo principal de la lambda
            main_file = os.path.join(source_dir, 'lambda_function.py')
            if os.path.exists(main_file):
                # Escribir el archivo en la raíz del zip
                zf.write(main_file, arcname='lambda_function.py')
                logger.info(f"Añadido: lambda_function.py")
            else:
                logger.error(f"¡Error! No se encontró {main_file}")
                return False

        logger.info(f"Paquete .zip creado exitosamente en {zip_name}")
        return True
        
    except Exception as e:
        logger.error(f"Error al crear el archivo zip: {e}")
        return False

if __name__ == '__main__':
    # Esto permite ejecutar el script directamente para probarlo
    # (El script de deploy.py lo importará como un módulo)
    
    # Obtener el directorio base del proyecto (un nivel arriba de 'infra')
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.dirname(BASE_DIR)
    
    # Definir rutas de origen y destino
    SOURCE_LAMBDA_DIR = os.path.join(PROJECT_ROOT, 'lambdas', 'load_inventory')
    BUILD_DIR = os.path.join(PROJECT_ROOT, 'build')
    OUTPUT_ZIP = os.path.join(BUILD_DIR, 'load_inventory.zip')

    # Crear el paquete
    package_lambda_function(SOURCE_LAMBDA_DIR, OUTPUT_ZIP)