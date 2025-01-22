ifeq ($(CC65),)
CC65=cc65
LD65=ld65
CA65=ca65
endif

hello.prg: hello.c text.s
	$(CC65) -g -O -t c64 $<
	$(CA65) -g $(basename $<).s
	$(CA65) -g -t c64 text.s
	$(LD65) -o $@ --dbgfile $(basename $@).ld65.dbg -t c64 $(basename $<).o text.o c64.lib
	$(PYTHON) python convert_ld65_to_kickasm_dbg_format.py $(basename $@).ld65.dbg -o $(basename $@).dbg

.PHONY: clean
clean:
	$(RM) *.o *.dbg hello.s *.prg