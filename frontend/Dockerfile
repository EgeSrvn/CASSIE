ARG NODE_BASE_IMAGE=node:20-alpine
ARG NGINX_BASE_IMAGE=nginx:1.27-alpine
FROM ${NODE_BASE_IMAGE} AS build

WORKDIR /app

ARG VITE_API_URL=
ARG VITE_GOOGLE_DRIVE_CLIENT_ID=
ARG VITE_GOOGLE_DRIVE_API_KEY=
ARG VITE_GOOGLE_DRIVE_APP_ID=
ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_GOOGLE_DRIVE_CLIENT_ID=${VITE_GOOGLE_DRIVE_CLIENT_ID}
ENV VITE_GOOGLE_DRIVE_API_KEY=${VITE_GOOGLE_DRIVE_API_KEY}
ENV VITE_GOOGLE_DRIVE_APP_ID=${VITE_GOOGLE_DRIVE_APP_ID}

COPY frontend/package*.json ./
RUN npm ci --fetch-retries=5 --fetch-retry-mintimeout=5000 --fetch-retry-maxtimeout=60000

COPY frontend/ ./
RUN npm run build

FROM ${NGINX_BASE_IMAGE}

COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
