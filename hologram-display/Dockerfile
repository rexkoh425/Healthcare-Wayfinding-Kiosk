FROM nginx:alpine

# Remove default static assets
RUN rm -rf /usr/share/nginx/html/*

# Copy all hologram-display contents to the nginx web root
COPY . /usr/share/nginx/html

# Remove any config that ends up in the static root and stage HTTPS config
RUN rm -f /usr/share/nginx/html/nginx.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose HTTP for redirects and HTTPS for the main site
EXPOSE 80
EXPOSE 443

# Start nginx in the foreground
CMD ["nginx", "-g", "daemon off;"]
