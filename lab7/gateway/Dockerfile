# Lab 7 gateway: Nginx reverse proxy and load balancer in front of the API replicas
FROM nginx:1.28-alpine

# The stock image renders /etc/nginx/templates/*.template into conf.d/ with
# envsubst at startup, so API_HOST, API_PORT and GATEWAY_PORT are set at run time.
RUN rm /etc/nginx/conf.d/default.conf && mkdir -p /var/log/nginx/lab7
COPY templates/ /etc/nginx/templates/

ENV API_HOST=api \
    API_PORT=8100 \
    GATEWAY_PORT=3204

EXPOSE 3204

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null "http://127.0.0.1:${GATEWAY_PORT}/gateway-health" || exit 1
