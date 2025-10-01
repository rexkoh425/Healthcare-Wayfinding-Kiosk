FROM nginx:alpine

# Remove default static assets
RUN rm -rf /usr/share/nginx/html/*

# Copy all hologram-display contents to the nginx web root
COPY . /usr/share/nginx/html

# Expose port 80 (this will be mapped to 3001 when running)
EXPOSE 80

# Start nginx in the foreground
CMD ["nginx", "-g", "daemon off;"]