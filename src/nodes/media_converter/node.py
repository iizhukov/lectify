import pathlib

from pydub import AudioSegment

from src.nodes.basenode import BaseNode
from src.nodes.media_converter.models import MediaConverterInput, MediaConverterOutput
from src.db.models import NodeStatus


class MediaConverterNode(BaseNode):
    def __init__(self):
        super().__init__(
            node_id="media_converter",
            name="Конвертация медиа-файла",
            input_model=MediaConverterInput,
            output_model=MediaConverterOutput
        )

    def run(self, input_data: MediaConverterInput, client) -> MediaConverterOutput:
        file_id = input_data.file_id
        file_path = input_data.file_path
        
        self.update_status(file_id, NodeStatus.RUNNING, "Конвертация медиа-файла в M4A...")
        try:
            input_path = pathlib.Path(file_path)
            output_path = input_path.with_suffix(".m4a")

            if input_path.suffix.lower() == ".m4a":
                self.update_status(file_id, NodeStatus.COMPLETED, "Конвертация не требуется (файл уже M4A)", str(input_path))
                return MediaConverterOutput(file_id=file_id, media_path=str(input_path))

            audio = AudioSegment.from_file(str(input_path))
            audio.export(str(output_path), format="ipod", codec="aac", bitrate="64k")

            self.update_status(file_id, NodeStatus.COMPLETED, "Файл успешно сконвертирован в M4A!", str(output_path))
            return MediaConverterOutput(file_id=file_id, media_path=str(output_path))
        except Exception as e:
            self.update_status(file_id, NodeStatus.FAILED, f"Ошибка при конвертации: {str(e)}")
            raise e
