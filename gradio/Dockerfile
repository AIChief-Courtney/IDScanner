FROM python:3.8-slim
USER root
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libgtk-3-0 \
    libx11-xcb1 \
    libxt6 \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /home/kby-ai-deepfake
WORKDIR /home/kby-ai-deepfake
COPY ./app.py .
COPY ./demo.py .
COPY ./invoice_ocr.py .
COPY ./requirements.txt .
COPY ./run.sh .
COPY ./examples ./examples
RUN chmod a+x run.sh
RUN pip3 install -r requirements.txt

# Set environment variables for Python and shared libraries
ENV PYTHONPATH=/home/kby-ai-deepfake
ENV LD_LIBRARY_PATH=/home/kby-ai-deepfake:$LD_LIBRARY_PATH

RUN ldconfig /home/kby-ai-deepfake
RUN playwright install chromium
RUN python3 -m camoufox fetch
RUN cat /etc/os-release
EXPOSE 7860
CMD ["/bin/bash", "/home/kby-ai-deepfake/run.sh"]
