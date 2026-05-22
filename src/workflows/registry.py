from src.workflows.workflow import Workflow
from src.nodes.media_converter.node import MediaConverterNode
from src.nodes.speech_to_text.node import S2TNode
from src.nodes.text_to_md.node import TextToMDNode
from src.nodes.text_to_latex.node import TextToLatexNode
from src.nodes.latex_to_pdf.node import LatexToPDFNode


def create_lecture_workflow() -> Workflow:
    media_converter = MediaConverterNode()
    speech_to_text = S2TNode()
    text_to_md = TextToMDNode()
    text_to_latex = TextToLatexNode()
    latex_to_pdf = LatexToPDFNode()

    media_converter.add_child(speech_to_text)
    speech_to_text.add_child(text_to_md)
    speech_to_text.add_child(text_to_latex)
    text_to_latex.add_child(latex_to_pdf)

    return Workflow(name="Lecture Conspectus Workflow", root_node=media_converter)


WORKFLOW_REGISTRY = {
    "lecture_workflow": create_lecture_workflow()
}
