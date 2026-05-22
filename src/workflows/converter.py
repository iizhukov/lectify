from src.nodes.media_converter.models import MediaConverterOutput
from src.nodes.speech_to_text.models import SpeechToTextInput, SpeechToTextOutput
from src.nodes.text_to_md.models import TextToMDInput
from src.nodes.text_to_latex.models import TextToLatexInput, TextToLatexOutput
from src.nodes.latex_to_pdf.models import LatexToPDFInput


def convert_media_out_to_stt_in(out_data: MediaConverterOutput) -> SpeechToTextInput:
    return SpeechToTextInput(file_id=out_data.file_id, media_path=out_data.media_path)


def convert_stt_out_to_md_in(out_data: SpeechToTextOutput) -> TextToMDInput:
    return TextToMDInput(file_id=out_data.file_id, txt_path=out_data.txt_path)


def convert_stt_out_to_latex_in(out_data: SpeechToTextOutput) -> TextToLatexInput:
    return TextToLatexInput(file_id=out_data.file_id, txt_path=out_data.txt_path)


def convert_latex_out_to_pdf_in(out_data: TextToLatexOutput) -> LatexToPDFInput:
    return LatexToPDFInput(file_id=out_data.file_id, latex_path=out_data.latex_path)


CONVERTER_REGISTRY = {
    (MediaConverterOutput, SpeechToTextInput): convert_media_out_to_stt_in,
    (SpeechToTextOutput, TextToMDInput): convert_stt_out_to_md_in,
    (SpeechToTextOutput, TextToLatexInput): convert_stt_out_to_latex_in,
    (TextToLatexOutput, LatexToPDFInput): convert_latex_out_to_pdf_in
}


def get_converter(from_cls, to_cls):
    """Возвращает конвертер для двух типов моделей, если он зарегистрирован"""
    return CONVERTER_REGISTRY.get((from_cls, to_cls))
