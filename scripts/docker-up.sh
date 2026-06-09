#!/bin/bash
cd /home/dydwls/DocuMind
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d
