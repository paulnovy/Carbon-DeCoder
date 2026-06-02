FROM node:20.15.1-alpine
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
ARG NEXT_PUBLIC_API_BASE_URL=
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
COPY package.json package-lock.json* jsconfig.json* postcss.config.js* tailwind.config.js* /app/
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY src /app/src
COPY public /app/public
RUN npm run build
EXPOSE 3000
CMD ["npm", "run", "start", "--", "-H", "0.0.0.0", "-p", "3000"]
