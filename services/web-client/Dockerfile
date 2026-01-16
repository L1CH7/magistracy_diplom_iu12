FROM node:18-slim as builder

WORKDIR /app

# Copy package.json from service directory
COPY services/web-client/package.json .
RUN npm config set fetch-retry-maxtimeout 60000 && \
    npm config set fetch-timeout 60000
RUN --mount=type=cache,target=/root/.npm \
    npm install --no-optional --no-audit --verbose && \
    npm install @rollup/rollup-linux-x64-gnu --no-save --verbose

# Copy source code from service directory
COPY services/web-client/ .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY services/web-client/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
