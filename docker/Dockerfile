FROM sengokucola/maibot@sha256:ada1d38593fe4756cc1b8af100ec62136d0e011416cd2cfd7908cdb1422443eb
RUN uv pip install --python /MaiMBot/.venv/bin/python 'silk-python==0.2.8'
COPY docker/patches/maibot-1.4.3-image-delivery.patch /tmp/maibot-image-delivery.patch
RUN git -C /MaiMBot apply /tmp/maibot-image-delivery.patch && rm /tmp/maibot-image-delivery.patch
