FROM python:3.11

# set working dir
WORKDIR /app

# install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY setup.sh .
RUN bash setup.sh

# copy app code
COPY . .

# expose port & launch
EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000"]


