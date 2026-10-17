def parse_line(line, delim=','):
    """RFC 4180-style single line. A quote opens a quoted field only at the start of a field; inside quotes a
    doubled quote is one literal quote and the delimiter is literal. Whitespace is preserved. A trailing delimiter
    yields a trailing empty field; '' parses to ['']. ValueError on an unterminated quote."""
    out, cur, inq = [], '', False
    for c in line:
        if c == '"':
            inq = not inq
        elif c == delim and not inq:
            out.append(cur)
            cur = ''
        else:
            cur += c
    if cur:
        out.append(cur)
    return out
