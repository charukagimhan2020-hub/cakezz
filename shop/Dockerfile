FROM php:8.2-apache
# curl extension ships with the official image; fail the build early if it is ever missing
RUN php -m | grep -qi '^curl$'
# listen on $PORT (Render sets it; default 80)
ENV PORT=80 APP_ENV=production
RUN sed -i 's/Listen 80/Listen ${PORT}/' /etc/apache2/ports.conf \
 && sed -i 's/<VirtualHost \*:80>/<VirtualHost *:${PORT}>/' /etc/apache2/sites-available/000-default.conf \
 && printf '<DirectoryMatch "^/var/www/html/includes">\n    Require all denied\n</DirectoryMatch>\n<FilesMatch "^\\.env">\n    Require all denied\n</FilesMatch>\n' > /etc/apache2/conf-available/cakezz-security.conf \
 && a2enconf cakezz-security
COPY . /var/www/html/
RUN chown -R www-data:www-data /var/www/html
EXPOSE 80
