def parse_line(line, delim=','):
    """RFC 4180-style single line. A quote opens a quoted field only at the start of a field; inside quotes a
    doubled quote is one literal quote and the delimiter is literal. Whitespace is preserved. A trailing delimiter
    yields a trailing empty field; '' parses to ['']. ValueError on an unterminated quote."""
    out, cur, inq, i, n = [], [], False, 0, len(line)
    while i < n:
        c = line[i]
        if inq:
            if c == '"':
                if i + 1 < n and line[i + 1] == '"':
                    cur.append('"')
                    i += 1
                else:
                    inq = False
            else:
                cur.append(c)
        elif c == '"' and not cur:
            inq = True
        elif c == delim:
            out.append(''.join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    if inq:
        raise ValueError('unterminated quote')
    out.append(''.join(cur))
    return out
