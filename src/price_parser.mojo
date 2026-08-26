"""Byte-oriented amount extraction for price strings."""

from std.sys import simd_width_of

comptime BPtr = Pointer[UInt8, AnyOrigin[mut=True]]
comptime IPtr = Pointer[Int64, AnyOrigin[mut=True]]


def is_digit(c: UInt8) -> Bool:
    return c >= UInt8(48) and c <= UInt8(57)


def is_space(c: UInt8) -> Bool:
    return (
        c == UInt8(32)
        or c == UInt8(9)
        or c == UInt8(10)
        or c == UInt8(11)
        or c == UInt8(12)
        or c == UInt8(13)
    )


def in_number(c: UInt8) -> Bool:
    return (
        is_digit(c)
        or is_space(c)
        or c == UInt8(46)
        or c == UInt8(44)
        or c == UInt8(39)
    )


def find_candidate(data: BPtr, begin: Int, end: Int) -> Int:
    comptime W = simd_width_of[DType.uint8]()
    var pos = begin
    while pos + W <= end:
        var chars = data.unsafe_load[width=W](pos)
        var candidates = chars.ge(48) & chars.le(57) | chars.eq(46)
        if candidates.cast[DType.uint8]().reduce_add():
            for lane in range(W):
                var c = data[unsafe_offset=pos + lane]
                if is_digit(c) or c == UInt8(46):
                    return pos + lane
        pos += W
    while pos < end:
        var c = data[unsafe_offset=pos]
        if is_digit(c) or c == UInt8(46):
            return pos
        pos += 1
    return end


def extract_amount(data: BPtr, begin: Int, end: Int) -> SIMD[DType.int64, 2]:
    var pos = begin
    while pos < end:
        pos = find_candidate(data, pos, end)
        if pos == end:
            break
        var start = pos
        if (
            data[unsafe_offset=pos] == UInt8(46)
            and pos + 1 < end
            and is_digit(data[unsafe_offset=pos + 1])
        ):
            pos += 2
        elif is_digit(data[unsafe_offset=pos]):
            pos += 1
        else:
            pos += 1
            continue

        while pos < end and in_number(data[unsafe_offset=pos]):
            pos += 1

        var stop = pos
        if pos == end or (
            not is_digit(data[unsafe_offset=pos])
            and data[unsafe_offset=pos] != UInt8(37)
        ):
            return SIMD[DType.int64, 2](
                Int64(start - begin), Int64(stop - begin)
            )

        # A blocked percent terminator can still make preceding whitespace or
        # punctuation terminate the regex match after backtracking.
        var back = stop - 1
        while back >= start and is_space(data[unsafe_offset=back]):
            back -= 1
        if back < stop - 1:
            return SIMD[DType.int64, 2](
                Int64(start - begin), Int64(back + 1 - begin)
            )
        while back > start:
            if (
                is_space(data[unsafe_offset=back])
                or data[unsafe_offset=back] == UInt8(46)
                or data[unsafe_offset=back] == UInt8(44)
                or data[unsafe_offset=back] == UInt8(39)
            ):
                return SIMD[DType.int64, 2](
                    Int64(start - begin), Int64(back - begin)
                )
            back -= 1
        pos = start + 1

    return SIMD[DType.int64, 2](-1, -1)


@export("mpp_extract_one")
def mpp_extract_one(data_addr: Int, n: Int, result_addr: Int) abi("C") -> Int64:
    if result_addr == 0 or n < 0 or (n > 0 and data_addr == 0):
        return -1

    var result = IPtr(unsafe_from_address=result_addr)
    if n == 0:
        result[unsafe_offset=0] = -1
        result[unsafe_offset=1] = -1
        return 0

    var data = BPtr(unsafe_from_address=data_addr)
    var span = extract_amount(data, 0, n)
    result[unsafe_offset=0] = span[0]
    result[unsafe_offset=1] = span[1]
    return 0


@export("mpp_extract_many")
def mpp_extract_many(
    data_addr: Int,
    data_len: Int,
    offsets_addr: Int,
    count: Int,
    starts_addr: Int,
    ends_addr: Int,
) abi("C") -> Int64:
    if (
        data_len < 0
        or count < 0
        or offsets_addr == 0
        or (count > 0 and (starts_addr == 0 or ends_addr == 0))
        or (data_len > 0 and data_addr == 0)
    ):
        return -1

    var offsets = IPtr(unsafe_from_address=offsets_addr)
    if offsets[unsafe_offset=0] != 0:
        return -2
    for i in range(count):
        if (
            offsets[unsafe_offset=i] < 0
            or offsets[unsafe_offset=i] > offsets[unsafe_offset=i + 1]
        ):
            return -2
    if offsets[unsafe_offset=count] > Int64(data_len):
        return -2
    if count == 0:
        return 0

    # The data pointer may be a non-dereferenceable sentinel only when every
    # input is empty. extract_amount does not load from an empty range.
    var data = BPtr(unsafe_from_address=data_addr)
    var starts = IPtr(unsafe_from_address=starts_addr)
    var ends = IPtr(unsafe_from_address=ends_addr)

    for i in range(count):
        var begin = Int(offsets[unsafe_offset=i])
        var span = extract_amount(
            data, begin, Int(offsets[unsafe_offset=i + 1])
        )
        starts[unsafe_offset=i] = span[0]
        ends[unsafe_offset=i] = span[1]
    return 0
