# WIP ld65 debuginfo converter. 
# stein.pedersen@gmail.com - 4-sep-2024

from argparse import ArgumentParser
from glob import glob
from typing import Dict, List, Tuple, Union
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
import sys

DefinitionItemValue = Union[str,int,List[int]]
DefinitionItemDict = Dict[str, DefinitionItemValue]
DefinitionList = List[Tuple[str,DefinitionItemDict]]

DefinitionDict = Dict[int, DefinitionItemDict]

MINIMUM_SUPPORTED_VERSION=(2,0) # ld65 dbginfo format version

SYMBOL_SIZE = { 'absolute': 2, 'zeropage': 1 }

VERBOSE = False
QUIET = False

def log(*args, **kwargs):
    if VERBOSE and not QUIET:
        print(*args, file=sys.stderr, **kwargs)

def log_normal(*args, **kwargs):
    if not QUIET:
        print(*args, file=sys.stderr, **kwargs)

p = ArgumentParser(description="Convert ld65 debug info file to Kick Assembler format usable by Retro Debugger.")
p.add_argument('input_file', metavar='FILE', nargs='?', help='File to convert.')
p.add_argument('-o', '--output-file', type=str, help='Output filename.')
p.add_argument('-v', '--verbose',   action='store_true', help='Display conversion information.')
p.add_argument('-q', '--quiet', action='store_true', help='Print no status information.')
args = p.parse_args()
VERBOSE = args.verbose
QUIET = args.quiet

def try_transform(token: str):
    if '+' in token:
        return [try_transform(t) for t in token.split('+')]
    elif token.startswith('0x'):
        return int(token, 16)
    elif token[0].isdigit():
        return int(token)
    elif token[:1]=='"' and token[-1:]=='"' and len(token) >= 2:
        return token[1:-1] # I don't know if characters can be escaped in this format
    else: # Enum type token?
            return token

def filter_items(key: str, items: DefinitionList) -> DefinitionDict:
    filtered_items = { definition['id']: { k:v for k,v in definition.items() if k!='id' } for title, definition in items if title == key }
    return filtered_items

glob_pattern = args.input_file if args.input_file is not None else ''
files = glob(glob_pattern)
if not files and not '*' in glob_pattern and glob_pattern:
    print(f'File not found "{glob_pattern}"')
    sys.exit(1)
elif len(files):
    for file in files:
        log(f'Parsing {file}')
        with open(file) as infile:
            lines = infile.readlines()
        tokenized = [(t[0], t[1].split(',')) for t in [line.split() for line in lines]]
        assert all([all([t.count('=') == 1 for t in items]) for name, items in tokenized]), "File format not recognized!"
        all_items = [ (name, { k: try_transform(v) for k, v in [item.split('=') for item in items] }) for name, items in tokenized ]
        assert all_items[0][0] == 'version' and 'major' in all_items[0][1] and 'minor' in all_items[0][1], "File format not recognized, expected version information."
        ver = (all_items[0][1]['major'], all_items[0][1]['minor'])
        assert ver >= MINIMUM_SUPPORTED_VERSION, f'Unsupported version {ver}. Supported is >= {MINIMUM_SUPPORTED_VERSION}'
        LABELS = filter_items('sym', all_items)
        FILES = filter_items('file', all_items)
        LINES = filter_items('line', all_items)
        MODULES = filter_items('mod', all_items)
        SEGMENTS = filter_items('seg', all_items)
        SPANS = filter_items('span', all_items)
        SCOPES = filter_items('scope', all_items)
        TYPES = filter_items('type', all_items)
        
        indent = '    '
        root = ET.Element('C64debugger', version="1.0")

        def format_addr(value: int, mode=None) -> str:
            return f'${value:04x}'
        
        def format_element_text(lines: List[str]) -> str:
            tmp = '\n'.join(lines)
            return f'\n{tmp}\n{indent}'

        def spans_filtered_on_segment(segment_id: int):
            spans = [s for s, d in SPANS.items() if d['seg']==segment_id ]
            return spans

        def format_file_line_begin_end(line_id: int, line_length: int = 1) -> str:
            line_def = LINES[line_id]
            file_id = line_def['file']
            lineno = line_def['line']
            col_begin = 1
            col_end = col_begin + line_length
            return f'{file_id},{lineno},{col_begin},{lineno},{col_end}'

        # Sources        
        sources = ET.SubElement(root, 'Sources', values="INDEX,FILE")
        sources_lines = [ f'{indent}{indent}{id},{items["name"]}' for id, items in FILES.items() ]
        sources.text = format_element_text(sources_lines)

        # Segments
        candidate_lines = { id: line_def for id, line_def in LINES.items() if 'span' in line_def }
        for seg_id, segment_def in SEGMENTS.items():
            segment = ET.SubElement(root, 'Segment', name=segment_def['name'], dest="", values="START,END,FILE_IDX,LINE1,COL1,LINE2,COL2")
            block = ET.SubElement(segment, 'Block', name="Basic")
            candidate_spans = spans_filtered_on_segment(seg_id)
            block_lines = []
            line_spans = []
            for line_id, line_def in candidate_lines.items():
                if line_def['span'] in candidate_spans:
                    line_spans.append((line_id, line_def['span']))
            for line_id, span_id in line_spans:
                span_def = SPANS[span_id]
                seg_base = segment_def['start']
                span_start = seg_base + span_def['start']
                span_end = span_start + span_def['size'] - 1
                line_info = format_file_line_begin_end(line_id)
                this_line = f'{indent}{indent}{indent}{format_addr(span_start)},{format_addr(span_end)},{line_info}'
                block_lines.append((span_start, this_line))
            sorted_lines = [ txt for addr, txt in sorted(block_lines) ]
            block.text = format_element_text(sorted_lines) + indent

        # Labels
        labels = ET.SubElement(root, 'Labels', values="SEGMENT,ADDRESS,NAME,START,END,FILE_IDX,LINE1,COL1,LINE2,COL2")
        label_lines = []
        for lbl_id, lbl in LABELS.items():
            if 'parent' in lbl:
                continue # this is a local label
            if not 'seg' in lbl:
                continue # .equ ?
            segment_def = SEGMENTS[lbl['seg']]
            name = lbl['name']
            addr = format_addr(lbl['val'])
            seg_name = segment_def['name']
            line_info = format_file_line_begin_end(lbl['def'], line_length=len(name))
            this_line = f'{indent}{indent}{seg_name},{addr},{name},{line_info}'
            label_lines.append(this_line)
        labels.text = format_element_text(label_lines)

        # Watchpoints        
        watchpoints = ET.SubElement(root, 'Watchpoints', values="SEGMENT,ADDRESS,ARGUMENT")
        
        # Breakpoints        
        breakpoints = ET.SubElement(root, 'Breakpoints', values="SEGMENT,ADDRESS,ARGUMENT")

        xml_str = ET.tostring(root, encoding='utf-8')
        parsed_xml = minidom.parseString(xml_str)
        pretty_xml_str = parsed_xml.toprettyxml(indent=indent)

        if args.output_file:
            with open(args.output_file, 'w') as outfile:
                print(pretty_xml_str, file=outfile)
            log_normal(f'Wrote "{args.output_file}') 
        else:       
            print(pretty_xml_str)
#        ET.indent(tree, space="    ", level=0)
#        tree.write('formatted_output.xml') #, encoding='utf-8', xml_declaration=True)
#        print(ET.tostring(root, encoding='utf-8', xml_declaration=True))
else:
    if glob_pattern:
        print(f'Nothing to do for "{glob_pattern}".')
    else:
        print("Nothing to do.")
