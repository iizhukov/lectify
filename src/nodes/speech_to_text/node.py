import pathlib
from pydub import AudioSegment

from src.nodes.basenode import BaseNode
from src.nodes.speech_to_text.models import SpeechToTextInput, SpeechToTextOutput
from src.db.models import NodeStatus


class S2TNode(BaseNode):
    def __init__(self):
        super().__init__(
            node_id="speech_to_text",
            name="Распознавание речи",
            input_model=SpeechToTextInput,
            output_model=SpeechToTextOutput
        )

    def run(self, input_data: SpeechToTextInput, client) -> SpeechToTextOutput:
        file_id = input_data.file_id
        file_path = input_data.media_path

        self.update_status(file_id, NodeStatus.RUNNING, "Распознавание речи (русский язык)...")
        try:
            audio = AudioSegment.from_file(file_path)
            duration_ms = len(audio)
            chunk_length_ms = 20 * 60 * 1000  # 20 минут
            
            stt_client = client.get_client()
            stt_model = client.get_model_name("stt")

            if duration_ms <= chunk_length_ms:
                with open(file_path, "rb") as audio_file:
                    transcript_response = stt_client.audio.transcriptions.create(
                        model=stt_model,
                        file=audio_file,
                        language="ru"
                    )

                full_text = transcript_response.text
            else:
                chunks = []
                for i in range(0, duration_ms, chunk_length_ms):
                    chunks.append(audio[i : i + chunk_length_ms])
                
                full_text_parts = []
                for idx, chunk in enumerate(chunks):
                    self.update_status(file_id, NodeStatus.RUNNING, f"Распознавание речи (часть {idx+1} из {len(chunks)})...")
                    chunk_path = pathlib.Path(file_path).parent / f"chunk_{file_id}_{idx}.mp3"
                    chunk.export(str(chunk_path), format="mp3", bitrate="64k")
                    
                    try:
                        with open(str(chunk_path), "rb") as audio_file:
                            transcript_response = stt_client.audio.transcriptions.create(
                                model=stt_model,
                                file=audio_file,
                                language="ru"
                            )
                        full_text_parts.append(transcript_response.text)
                    finally:
                        if chunk_path.exists():
                            chunk_path.unlink()
                
                full_text = " ".join(full_text_parts)
                
            txt_path = str(pathlib.Path(file_path).with_suffix(".txt"))
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(full_text)
                
            self.update_status(file_id, NodeStatus.COMPLETED, "Речь успешно распознана!", txt_path)
            return SpeechToTextOutput(file_id=file_id, txt_path=txt_path)
        except Exception as e:
            self.update_status(file_id, NodeStatus.FAILED, f"Ошибка: {str(e)}")
            raise e
