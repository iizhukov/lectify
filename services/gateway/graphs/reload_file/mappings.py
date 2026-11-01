def left_request(ctx):
    return {'id': ctx.input.file_id}


def reload_request(ctx):
    return {'id': ctx.parents['left'].id}


def response(ctx):
    left, right = ctx.parents['left'], ctx.parents['right']
    return {
        'left': {'id': left.id, 'filename': left.filename},
        'right': {'id': right.id, 'filename': right.filename},
        'same_content': left.sha256 == right.sha256,
    }
