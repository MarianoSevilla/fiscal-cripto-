# Acceso lento: corrección del feedback y diagnóstico

Base: producción 3d2a83191c0d8b604a9aa7956098ab559108aca6. Trabajo autorizado el 18/10/2026; publicación pendiente.

## Evidencia

En la ventana del incidente, Railway registró dos POST /api/login con HTTP499 a 15007 y 14986 ms (cliente cerró la petición), y un acceso posterior HTTP200 en210ms. Dashboard200 en9ms. El cliente abortaba mediante AbortController a15000ms. Las métricas consultadas no muestran saturación de CPU/memoria. No hay trazas de fases para esos dos intentos: no se atribuye la causa a PostgreSQL, bcrypt, red o arranque sin evidencia. Los tiempos HTTP no equivalen a tiempo total percibido por el usuario.

## Cambio

Solo login: aviso role=status a8s sin mover foco ni cancelar. Una petición pendiente mantiene botón deshabilitado; un submit repetido se ignora. Se espera hasta45s como máximo. Éxito navega al destino seguro; error/timeout elimina aviso y permite reintentar. No se reenvían credenciales automáticamente. Resto de formularios conserva su límite15s. El nuevo límite no demuestra una mejora de latencia del servidor.

Servidor: AUTH_LOGIN_TIMING con referencia aleatoria por petición, inicio/fin total y fases account_lookup, password_check, verification_email, last_login_commit, session_create. Reloj monotónico; logger propio INFO a stderr, sin cambiar el nivel del logger general. No recibe correo, contraseña, ID de usuario, tokens, IP, query, cuerpo o contenido de excepciones. Los nombres de fase tienen lista cerrada. No se debilitan bcrypt, sesiones, verificación, límites, OIDC ni controles de origen. Sin dependencias, migraciones o cambios de infraestructura.

Estas mediciones empiezan al entrar en la vista: no miden la espera previa en proxy, transporte, cuerpo HTTP o middleware/límite de peticiones. Se compararán con logs HTTP para distinguir esas esperas. Si vuelve a ocurrir, una fase con inicio sin fin permitirá localizar una espera activa; la ausencia de inicio no demuestra por sí sola su causa.

## Validación

Tres pruebas unitarias de duraciones/excepciones/ausencia de datos privados, con reloj y logger simulados. Tres escenarios nuevos de navegador con reloj virtual y respuesta interceptada: éxito después17s, error después17s y cancelación a45s. Se conservan pruebas de seguridad y responsive. Captura del aviso lento con datos ficticios en artefacto CI. Resultados finales en la PR.

Ningún login, email o cuenta real utilizado para probar el cambio. Producción permanece intacta hasta autorización de publicación. Tras publicar se podrá observar un nuevo intento real del titular; aún no se garantiza identificada o resuelta la causa original.
