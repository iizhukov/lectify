"""Ready-to-fork backend graphs; no transport, credentials or executable expressions."""
import json

PROMPTS={
    'markdown':dict(name='Lectify: конспект Markdown',
        system_prompt='Составь подробный структурированный конспект на русском языке в Markdown. Сохрани факты, определения и примеры. Не придумывай сведения.',
        user_prompt_template='{{transcript}}',variables=['transcript']),
    'latex':dict(name='Lectify: конспект LaTeX',
        system_prompt='Создай полный компилируемый LaTeX-конспект лекции. Используй T2A и babel russian для кириллицы. Верни только LaTeX без Markdown-ограждений.',
        user_prompt_template='{{transcript}}',variables=['transcript'])}


def build(prompt_ids):
    def node(id,plugin,parameters=None,mapping=None):
        return dict(id=id,plugin_id=plugin,plugin_version='1.1.0' if plugin in ('media_converter','speech_to_text') else '1.0.0',
            parameters_json=json.dumps(parameters or {},ensure_ascii=False),input_mapping=mapping or [])
    def edge(source,output,target,input):
        return dict(from_node_id=source,from_output=output,to_node_id=target,to_input=input)
    workflows=[]
    for kind in ('audio','video','text'):
        for output in ('markdown','pdf'):
            if kind=='text' and output=='pdf': continue
            nodes=[node('input','input',{'input_type':kind},[dict(target_field='file_id',source='input.file',transform='passthrough')])]
            edges=[]
            source,port='input','text'
            if kind!='text':
                nodes += [node('convert','media_converter'),node('transcribe','speech_to_text')]
                edges += [edge('input','data','convert','media'),edge('convert','audio','transcribe','audio')]
                source,port='transcribe','transcript'
            prompt_kind='markdown' if output=='markdown' else 'latex'
            nodes.append(node('prompt','prompt_selector',{'prompt_id':prompt_ids[prompt_kind]}))
            render_plugin='text_to_md' if output=='markdown' else 'text_to_latex'
            nodes.append(node('notes',render_plugin))
            edges += [edge(source,port,'notes','text'),edge('prompt','prompt','notes','prompt')]
            if output=='pdf':
                nodes.append(node('pdf','latex_to_pdf'))
                edges.append(edge('notes','latex','pdf','latex'))
            workflows.append(dict(name=f'Lectify: {kind} → {output}',
                description='Готовый сценарий монолита. Создайте свою копию и передайте ID загруженного файла во вход file.',
                graph=dict(nodes=nodes,edges=edges)))
    return workflows
