"""Turn Jira comment JSON into plain text."""


def comments_to_text(payload: dict) -> str:
    parts = []
    for comment in payload.get("comments", []):
        text = adf_to_text(comment.get("body")).strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def adf_to_text(node) -> str:
    """Read Atlassian document JSON, which is how Jira stores comments."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(adf_to_text(item) for item in node)
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text") or ""
        content = node.get("content") or []
        return " ".join(adf_to_text(item) for item in content).strip()
    return ""
