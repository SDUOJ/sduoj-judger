package cn.edu.sdu.qd.oj.judger.exception;

public class CompileErrorException extends Exception {
    public CompileErrorException() {
        super();
    }

    public CompileErrorException(String message, Throwable cause) {
        super(message, cause);
    }

    public CompileErrorException(String message) {
        super(message);
    }

    public CompileErrorException(Throwable cause) {
        super(cause);
    }
}
