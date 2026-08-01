FROM node:18-alpine

# Install ffmpeg for media processing (optional but recommended)
RUN apk add --no-cache ffmpeg

# Create app directory
WORKDIR /app

# Install node-media-server globally
RUN npm install -g node-media-server

# Copy optional configuration if you have one (you can mount a config file at runtime)
# VOLUME ["/app/config"]

# Expose common streaming ports
EXPOSE 1935 8000 8443

# Default command to run the server (you can override with custom config)
CMD ["npx", "node-media-server"]
