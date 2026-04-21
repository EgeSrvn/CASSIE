FROM node:20-alpine AS build

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
RUN npm ci

COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
