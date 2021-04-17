import codecs
import os
from collections import OrderedDict
from hacktools import common
import constants


def readString(f, invtable, ptrs=None):
    # Strings are "compressed" by skipping the first byte
    # if it's the same as the previous character
    group = 0
    ret = ""
    while True:
        byte = f.readByte()
        if ptrs is None and byte == 0:
            break
        if byte >= 0x90 and byte <= 0xa5:
            group = byte
        elif byte == 0xa:
            ret += "|"
        elif byte < 0xa:
            ret += "<" + common.toHex(byte) + ">"
            if ptrs is not None:
                while True:
                    if f.tell() in ptrs:
                        return formatString(ret)
                    lastchars = ret[-12:]
                    if lastchars == "<01><03><01>" or lastchars == "<01><03><02>" or lastchars == "<01><03><03>":
                        break
                    byte = f.readByte()
                    ret += "<" + common.toHex(byte) + ">"
        else:
            charcode = (group * 0x100) + byte
            if charcode not in invtable:
                common.logWarning("Charcode", common.toHex(charcode), "not found")
                ret += "<" + common.toHex(group) + ">"
                ret += "<" + common.toHex(byte) + ">"
                group = 0
            else:
                ret += invtable[charcode]
    return formatString(ret)


def readData(f, ptrs):
    byte = f.readByte()
    ret = "<" + common.toHex(byte) + ">"
    while f.tell() not in ptrs:
        byte = f.readByte()
        ret += "<" + common.toHex(byte) + ">"
    return ret


def formatString(str):
    while str.endswith("<00>"):
        str = str[:-4]
    for stringcode in constants.stringcodes:
        str = str.replace(stringcode, constants.stringcodes[stringcode])
    return str


def writeString(f, s, table, maxlen=-1):
    group = 0
    totlen = 0
    for stringcode in constants.stringcodes:
        s = s.replace(constants.stringcodes[stringcode], stringcode)
    x = 0
    while x < len(s):
        c = s[x]
        x += 1
        if c == "|":
            if maxlen != -1 and totlen + 1 > maxlen:
                common.logError("String", s, "is too long (" + str(x) + "/" + str(len(s)) + ")")
                break
            f.writeByte(0xa)
            totlen += 1
        elif c == "<":
            if maxlen != -1 and totlen + 1 > maxlen:
                common.logError("String", s, "is too long (" + str(x) + "/" + str(len(s)) + ")")
                break
            code = s[x] + s[x+1]
            f.write(bytes.fromhex(code))
            x += 3
            totlen += 1
        else:
            if c not in table:
                common.logError("Character", c, "not found for string", s)
            else:
                charcode = table[c][0]
                if len(table[c]) > 1:
                    # Pick the best one
                    for ci in range(1, len(table[c])):
                        checkgroup = table[c][ci] >> 8
                        if checkgroup == group:
                            charcode = table[c][ci]
                            break
                chargroup = charcode >> 8
                if group != chargroup:
                    if maxlen != -1 and totlen + 2 > maxlen:
                        common.logError("String", s, "is too long (" + str(x) + "/" + str(len(s)) + ")")
                        break
                    group = chargroup
                    f.writeByte(group)
                    f.writeByte(charcode & 0xff)
                    totlen += 2
                else:
                    if maxlen != -1 and totlen + 1 > maxlen:
                        common.logError("String", s, "is too long (" + str(x) + "/" + str(len(s)) + ")")
                        break
                    f.writeByte(charcode & 0xff)
                    totlen += 1
    f.writeByte(0)


def detectTextCode(s, i=0):
    if s[i] == "<":
        return len(s[i:].split(">", 1)[0]) + 1
    return 0


def getBINPointerGroups(f):
    datoffsets = []
    # Initialize allptr with the end of the last string
    allptrs = [0x13a3f4]
    datagroups = []
    allptrs.append(constants.mainptr["end"])
    ptrgroups = OrderedDict()
    for datptr in constants.datptrs:
        if type(constants.datptrs[datptr]) is list:
            for subdatptr in constants.datptrs[datptr]:
                datoffsets.append(subdatptr["offset"])
        else:
            offset = constants.datptrs[datptr]["offset"]
            datoffsets.append(offset)
            if "main" in constants.datptrs[datptr]:
                ptrgroups[offset] = []
            if "dataonly" in constants.datptrs[datptr]:
                datagroups.append(offset)
    f.seek(0xb12a8)
    while f.tell() < 0xb2810:
        ptrgroups[f.readUInt() - 0x02000000] = []
    for ptrgroup in ptrgroups:
        first = True
        f.seek(ptrgroup)
        datagroup = ptrgroup in datagroups
        while True:
            # Stop if we reach another ptr group
            if not first and (f.tell() in ptrgroups or f.tell() in datoffsets):
                break
            first = False
            ptrpos = f.tell()
            ptr = f.readUInt() - 0x02000000
            # Stop if we reach something that's not a pointer
            if ptr < 0 or ptr > 0x1d8000:
                break
            # Skip if the ptr is outside the main area
            if ptr < constants.mainptr["offset"] or ptr > constants.mainptr["end"]:
                continue
            allptrs.append(ptr)
            ptrgroups[ptrgroup].append({"pos": ptrpos, "ptr": ptr, "data": datagroup})
    return ptrgroups, allptrs


def getBMPOffsets(f, folder):
    ptrs = {}
    for file in constants.bmpptr:
        ptr = constants.bmpptr[file]
        ptrs[file] = []
        if type(ptr) is list:
            for offset in ptr:
                ptrs[file].append({"pos": 0, "size": 0, "offset": offset})
            continue
        f.seek(ptr)
        lastoff = -1
        filesize = os.path.getsize(folder + file)
        while True:
            offpos = f.tell()
            off = f.readUInt()
            size = f.readUInt()
            if off < lastoff or off > filesize:
                break
            if off < lastoff:
                continue
            lastoff = off
            ptrs[file].append({"pos": offpos, "size": size, "offset": off})
    return ptrs


def getTable(data):
    table = {}
    invtable = {}
    if not os.path.isfile(data + "table.txt"):
        common.logError("table.txt file not found")
        return table, invtable
    with codecs.open(data + "table.txt", "r", "utf-8") as tablef:
        section = common.getSection(tablef, "", comment="##")
    for code in section:
        glyph = section[code][0]
        glyph = glyph.replace("<3D>", "=")
        codehex = int(code, 16)
        if glyph not in table:
            table[glyph] = []
        table[glyph].append(codehex)
        invtable[codehex] = glyph
    return table, invtable


def getGlyphs(data):
    glyphs = {}
    if not os.path.isfile(data + "fontconfig.txt"):
        common.logError("fontconfig.txt file not found")
        return glyphs
    with codecs.open(data + "fontconfig.txt", "r", "utf-8") as f:
        fontconfig = common.getSection(f, "", comment="##")
        for c in fontconfig:
            charlen = 0 if fontconfig[c][0] == "" else int(fontconfig[c][0])
            c = c.replace("<3D>", "=")
            glyphs[c] = common.FontGlyph(0, charlen, charlen)
    return glyphs
