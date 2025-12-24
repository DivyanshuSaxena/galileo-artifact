CC = gcc
CFLAGS = -lm -pthread
TARGET = cpu_stress
SRC = CPU_stress.c

$(TARGET): $(SRC)
	$(CC) $(SRC) -o $(TARGET) $(CFLAGS)

clean:
	rm -f $(TARGET)