def get_url_to_visit(domain: str, subdomain_prefix: str) -> str:
    if not subdomain_prefix:
        return f"https://{domain}"
    if "#" in subdomain_prefix or "/" in subdomain_prefix:
        return f"https://{domain}"
    return f"https://{subdomain_prefix}.{domain}"
