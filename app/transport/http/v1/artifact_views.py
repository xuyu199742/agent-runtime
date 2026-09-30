def artifact_out(row):
    return {
        "id": row.id,
        "conversation_id": row.conversation_id,
        "run_id": row.run_id,
        "message_id": row.message_id,
        "name": row.name,
        "type": row.type,
        "mime_type": row.mime_type,
        "size": row.size,
        "metadata": row.metadata_,
        "created_at": row.created_at,
    }


def artifact_page(rows, total: int, page: int, page_size: int):
    return {
        "items": [artifact_out(row) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }
