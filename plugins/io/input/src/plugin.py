import codecs
import json

_TYPES = {'audio':'audio/','video':'video/','pdf':'application/pdf','text':'text/','image':'image/','any':''}


class PluginHandler:
    def __init__(self, context, sidecar):
        self.context,self.sidecar = context,sidecar
        self.selected = False

    async def on_start(self):
        if self.context.parameters.input_type not in _TYPES:
            raise ValueError('Unsupported input type')

    async def process_buffer(self, buffer):
        file_id = buffer.decode('utf-8')
        if self.selected or not file_id or file_id.strip()!=file_id or len(file_id)>128:
            raise ValueError('Exactly one valid file ID is required')
        self.selected = True
        info = await self.sidecar.get_file_info(file_id)
        mime = info['content_type'].split(';',1)[0].strip().lower()
        kind = self.context.parameters.input_type
        expected = _TYPES[kind]
        if expected and not (mime.startswith(expected) if expected.endswith('/') else mime==expected):
            raise ValueError('File MIME does not match the required input type')
        textual = mime.startswith('text/')
        decoder = codecs.getincrementaldecoder('utf-8-sig')() if textual else None
        async def outputs():
            yield {'metadata':json.dumps(info,ensure_ascii=False).encode('utf-8')}
            async for chunk in self.sidecar.read_file(file_id,chunk_size_bytes=65536):
                values = {'data':chunk}
                if decoder is not None:
                    text = decoder.decode(chunk)
                    if text: values['text'] = text.encode('utf-8')
                yield values
            if decoder is not None:
                text = decoder.decode(b'',final=True)
                if text: yield {'text':text.encode('utf-8')}
        return outputs()

    async def on_finish(self):
        if not self.selected:
            raise ValueError('File input is missing')
