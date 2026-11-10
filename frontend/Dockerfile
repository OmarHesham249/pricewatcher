FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY frontend/index.html /usr/share/nginx/html/index.html
COPY deploy/nginx/default.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
USER 101
