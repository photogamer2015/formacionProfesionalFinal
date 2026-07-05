#!/bin/bash

# ==============================================================================
# Script de Backup Seguro a AWS S3
# Este script es de solo lectura: no modifica ni daña la base de datos actual.
# ==============================================================================

# 1. Cargar las variables de entorno desde el archivo .env del proyecto
# Cambia esta ruta si tu archivo .env está en otro lugar
ENV_FILE="/var/www/formacion_tecnica_profesional/.env"
if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' $ENV_FILE | xargs)
else
    echo "❌ Error: No se encontró el archivo .env en $ENV_FILE"
    exit 1
fi

# Variables de la base de datos (tomadas del .env automáticamente)
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_NAME=$DB_NAME
DB_HOST=${DB_HOST:-"127.0.0.1"}

# Configuración del Backup
DATE=$(date +"%Y-%m-%d_%H-%M-%S")
BACKUP_DIR="/tmp/backups_erp"
FILE_NAME="backup_${DB_NAME}_${DATE}.sql.gz"
S3_BUCKET="s3://NOMBRE-DE-TU-BUCKET/backups_madrugada/" # ⚠️ REEMPLAZAR AQUÍ TU BUCKET S3 ⚠️

# Crear la carpeta temporal si no existe
mkdir -p "$BACKUP_DIR"
cd "$BACKUP_DIR" || exit

echo "Iniciando respaldo de la base de datos: $DB_NAME..."

# 2. Generar el backup comprimido usando mysqldump (solo lectura, seguro)
mysqldump -h "$DB_HOST" -u "$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" | gzip > "$FILE_NAME"

if [ $? -eq 0 ]; then
    echo "✅ Backup local creado con éxito: $FILE_NAME"
else
    echo "❌ Error al generar el backup local de la base de datos."
    exit 1
fi

# 3. Subir el archivo al bucket de S3
echo "Subiendo a AWS S3..."
aws s3 cp "$FILE_NAME" "$S3_BUCKET"

if [ $? -eq 0 ]; then
    echo "✅ Backup subido a S3 con éxito."
else
    echo "❌ Error al subir el backup a S3."
    # Opcional: enviar alerta por correo/telegram aquí
fi

# 4. Eliminar el archivo local para no ocupar espacio en el disco duro
rm -f "$FILE_NAME"
echo "🧹 Archivo temporal eliminado. Proceso finalizado."
