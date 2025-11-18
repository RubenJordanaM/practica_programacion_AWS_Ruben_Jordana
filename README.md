# Práctica Cloud Computing: Dashboard Serverless de Inventario

Este proyecto implementa una arquitectura **serverless en AWS** para cargar, procesar y visualizar inventario mediante Lambda, S3, DynamoDB y API Gateway. La infraestructura se despliega de forma programática con Python y `boto3`.

---

# 🚀 Flujo General

1. Se sube un archivo CSV al bucket S3 de **ingesta**.
2. S3 activa la **Lambda A** (`load_inventory`), que procesa el CSV y almacena los datos en **DynamoDB**.
3. Un sitio web estático (bucket S3 de **web**) consulta la **API Gateway**.
4. API Gateway invoca la **Lambda B** (`get_inventory_api`), que devuelve el inventario en JSON.
5. **DynamoDB Streams** activa la **Lambda C** (`notify_low_stock`) que publica alertas en **SNS**.

---

# 📂 Estructura del Proyecto

```
inventory-practice/
├─ infra/              # Scripts para desplegar y borrar la infraestructura
│  ├─ deploy.py        # Despliegue programático con boto3
│  ├─ teardown.py      # Borrar recursos
│  ├─ package_lambda.py# Empaquetado de lambdas
│  └─ requirements.txt # (boto3, python-dotenv)
├─ lambdas/            # Código de las tres lambdas
│  ├─ load_inventory/
│  ├─ get_inventory_api/
│  └─ notify_low_stock/
├─ web/                # Sitio web estático (index.html)
├─ .env                # Variables de entorno 
├─ .gitignore           
└─ README.md
```

---

# ⚙️ Recursos en AWS (prefijo `UNIQUE_PREFIX`)

* S3 Ingesta (uploads)
* S3 Web (sitio estático)
* DynamoDB (tabla de inventario)
* Lambda A: `load_inventory`
* Lambda B: `get_inventory_api`
* Lambda C: `notify_low_stock`
* API Gateway
* SNS (notificaciones)

---

# 🛠️ Despliegue

## 1. Prerrequisitos

* Python 3.11+
* Cuenta AWS (Learner Lab)
* Credenciales AWS temporales (o de usuario con permisos)
* Instalar dependencias:

```bash
cd infra/
pip install -r requirements.txt
```

## 2. Configuración

Crea el archivo `.env` en la raíz con estos valores (modifica según tu cuenta):

```ini
UNIQUE_PREFIX=TU_UNIQUE_PREFIX
AWS_REGION="us-east-1"
AWS_ACCOUNT_ID=TU_ACCOUNT_ID
NOTIFICATION_EMAIL=correo@ejemplo.com
```

> **Nota (Learner Lab):** los entornos de estudiante no permiten crear roles IAM. Usa el rol `LabRole` existente: copia su ARN desde la consola IAM y pégalo en `infra/deploy.py` (variable `STUDENT_ROLE_ARN` o dentro de `create_iam_roles()`).

## 3. Desplegar

Configura las credenciales en tu terminal (ejemplo macOS/Linux):

```bash
export AWS_ACCESS_KEY_ID="TU_KEY_ID"
export AWS_SECRET_ACCESS_KEY="TU_SECRET_KEY"
export AWS_SESSION_TOKEN="TU_SESSION_TOKEN"
```

Ejecuta el despliegue:

```bash
cd infra/
python deploy.py
```

Al terminar el script verás: URL del sitio web, endpoint de la API y el bucket para subir CSVs.

---

# ✅ Pruebas y Verificación

## 1. Confirmar suscripción SNS

Abre tu correo y confirma la suscripción enviada por AWS (enlace `Confirm subscription`).

## 2. Ingesta (S3 → Lambda A → DynamoDB)

Sube un CSV con inventario:

```bash
aws s3 cp inventory-berlin.csv s3://<UNIQUE_PREFIX>-inventory-uploads/
```

Comprueba que los elementos aparecen en la tabla DynamoDB.

## 3. Web + API (Web → API → Lambda B)

Abre la URL del sitio web proporcionada por `deploy.py` y verifica que muestra la tabla con inventario.

## 4. Alerta de Bajo Stock (DDB Stream → Lambda C → SNS)

Sube un CSV con un `Count` menor a 5 y revisa tu correo para recibir la alerta.

Ejemplo CSV:

```csv
Store,Item,Count
Berlin,Echo Spot,2
```

---

# 🧹 Limpieza (Teardown)

Para eliminar todos los recursos y evitar costes:

```bash
cd infra/
python teardown.py
```

El script pedirá tu `UNIQUE_PREFIX` (p. ej. `rjordana-practica25`) como confirmación.

---