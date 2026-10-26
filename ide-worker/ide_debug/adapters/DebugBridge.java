/* A restricted, dependency-free JDI adapter. Compile separately for each approved
 * JDK (JDK8 includes tools.jar). No evaluate, invokeMethod, REPL or host attach. */
import com.sun.jdi.*;
import com.sun.jdi.connect.*;
import com.sun.jdi.event.*;
import com.sun.jdi.request.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

public final class DebugBridge {
    private final VirtualMachine vm;
    private final String main;
    private final Map<Integer, StackFrame> frames = new HashMap<>();
    private final Map<Integer, Object> refs = new HashMap<>();
    private int handle = 1;
    private List<Integer> lines;
    private ThreadReference stopped;
    private final java.util.concurrent.BlockingQueue<byte[]> input = new java.util.concurrent.ArrayBlockingQueue<>(16);
    private final java.util.concurrent.atomic.AtomicInteger pendingInput = new java.util.concurrent.atomic.AtomicInteger();

    private DebugBridge(String[] args) throws Exception {
        main = args[1];
        lines = lines(args[2]);
        LaunchingConnector connector = Bootstrap.virtualMachineManager().defaultConnector();
        Map<String, Connector.Argument> config = connector.defaultArguments();
        config.get("main").setValue(main);
        String extra = new String(Base64.getDecoder().decode(args[3]), StandardCharsets.UTF_8);
        // This option list comes from the trusted manifest, not the browser.
        config.get("options").setValue("-cp " + args[0] + " " + extra.replace('\n', ' '));
        config.get("suspend").setValue("true");
        vm = connector.launch(config);
        Thread writer = new Thread(() -> {
            try {
                while (true) {
                    byte[] data = input.take();
                    try {
                        vm.process().getOutputStream().write(data);
                        vm.process().getOutputStream().flush();
                    } finally { pendingInput.addAndGet(-data.length); }
                }
            } catch (Exception ignored) { }
        }, "target-stdin");
        writer.setDaemon(true); writer.start();
        output(vm.process().getInputStream(), "stdout");
        output(vm.process().getErrorStream(), "stderr");
        ClassPrepareRequest prepare = vm.eventRequestManager().createClassPrepareRequest();
        prepare.addClassFilter(main + "*");
        prepare.setSuspendPolicy(EventRequest.SUSPEND_ALL);
        prepare.enable();
        if (lines.isEmpty()) {
            MethodEntryRequest entry = vm.eventRequestManager().createMethodEntryRequest();
            entry.addClassFilter(main); entry.addCountFilter(1);
            entry.setSuspendPolicy(EventRequest.SUSPEND_ALL); entry.enable();
        }
        Thread events = new Thread(() -> {
            try {
                while (true) {
                    EventSet set = vm.eventQueue().remove();
                    boolean stop = false;
                    for (Event event : set) {
                        if (event instanceof VMStartEvent) {
                            send(map("event", "running", "body", map()));
                        } else if (event instanceof ClassPrepareEvent) {
                            synchronized (this) { install(((ClassPrepareEvent) event).referenceType()); }
                        } else if (event instanceof BreakpointEvent || event instanceof StepEvent || event instanceof MethodEntryEvent) {
                            synchronized (this) {
                                stopped = ((LocatableEvent) event).thread();
                                frames.clear(); refs.clear(); handle = 1;
                                if (event instanceof StepEvent)
                                    vm.eventRequestManager().deleteEventRequest(((StepEvent) event).request());
                                send(map("event", "stopped", "body", map("threadId", stopped.uniqueID(),
                                        "reason", event instanceof StepEvent ? "step" : "breakpoint")));
                            }
                            stop = true;
                        } else if (event instanceof VMDeathEvent || event instanceof VMDisconnectEvent) {
                            send(map("event", "terminated", "body", map()));
                            return;
                        }
                    }
                    if (!stop) set.resume();
                }
            } catch (Exception e) { send(map("event", "terminated", "body", map())); }
        }, "jdi-events");
        events.setDaemon(true);
        events.start();
    }

    private synchronized void install(ReferenceType type) throws Exception {
        for (int line : lines) {
            try {
                List<Location> locations = type.locationsOfLine(line);
                for (Location location : locations) {
                    BreakpointRequest request = vm.eventRequestManager().createBreakpointRequest(location);
                    request.setSuspendPolicy(EventRequest.SUSPEND_ALL);
                    request.enable();
                }
            } catch (AbsentInformationException ignored) { }
        }
    }

    private ThreadReference thread(long id) {
        if (id == 0 && stopped != null) return stopped;
        for (ThreadReference one : vm.allThreads()) if (one.uniqueID() == id) return one;
        throw new IllegalArgumentException("Unknown thread");
    }

    private synchronized Object command(String[] f) throws Exception {
        String op = f[1];
        long tid = Long.parseLong(f[2]);
        if (op.equals("stdin")) {
            byte[] data = Base64.getDecoder().decode(f[8]);
            if (pendingInput.get() + data.length > 65536 || input.remainingCapacity() == 0)
                return map("acceptedBytes", 0, "error", "DEBUG_STDIN_BUFFER_FULL");
            pendingInput.addAndGet(data.length); input.add(data);
            return map("acceptedBytes", data.length);
        }
        if (op.equals("pause")) {
            vm.suspend();
            stopped = thread(tid);
            send(map("event", "stopped", "body", map("reason", "pause", "threadId", stopped.uniqueID())));
            return map();
        }
        if (op.equals("continue") || op.equals("next") || op.equals("stepIn") || op.equals("stepOut")) {
            if (!op.equals("continue")) {
                int depth = op.equals("next") ? StepRequest.STEP_OVER : op.equals("stepIn") ? StepRequest.STEP_INTO : StepRequest.STEP_OUT;
                StepRequest request = vm.eventRequestManager().createStepRequest(thread(tid), StepRequest.STEP_LINE, depth);
                request.addClassExclusionFilter("java.*");
                request.addClassExclusionFilter("jdk.*");
                request.addCountFilter(1);
                request.setSuspendPolicy(EventRequest.SUSPEND_ALL);
                request.enable();
            }
            frames.clear(); refs.clear(); stopped = null;
            send(map("event", "running", "body", map()));
            vm.resume();
            return map();
        }
        if (op.equals("threads")) {
            List<Object> out = new ArrayList<>();
            for (ThreadReference t : vm.allThreads()) {
                if (out.size() == 100) break;
                out.add(map("id", t.uniqueID(), "name", t.name()));
            }
            return map("threads", out);
        }
        if (op.equals("stackTrace")) {
            List<Object> out = new ArrayList<>();
            for (StackFrame frame : thread(tid).frames()) {
                if (out.size() == 100) break;
                int id = handle++; frames.put(id, frame);
                Location l = frame.location();
                out.add(map("id", id, "name", l.declaringType().name()+"."+l.method().name(),
                        "line", l.lineNumber(), "source", "/work/"+main+".java"));
            }
            return map("stackFrames", out);
        }
        if (op.equals("scopes")) {
            StackFrame frame = frames.get(Integer.parseInt(f[3]));
            if (frame == null) throw new IllegalArgumentException("Stale frame");
            int id = handle++; refs.put(id, frame);
            return map("scopes", Arrays.asList(map("name", "Locals", "variablesReference", id, "expensive", false)));
        }
        if (op.equals("variables")) {
            Object ref = refs.get(Integer.parseInt(f[4]));
            List<Object> out = new ArrayList<>();
            int start = Integer.parseInt(f[5]);
            int count = Math.min(100, Integer.parseInt(f[6]));
            if (ref instanceof StackFrame) {
                StackFrame frame = (StackFrame) ref;
                List<LocalVariable> locals = frame.visibleVariables();
                for (int i=start; i<locals.size() && out.size()<count; i++)
                    out.add(variable(locals.get(i).name(), frame.getValue(locals.get(i))));
            } else if (ref instanceof ArrayReference) {
                ArrayReference array = (ArrayReference) ref;
                for (int i=start; i<array.length() && out.size()<count; i++)
                    out.add(variable("["+i+"]", array.getValue(i)));
            } else if (ref instanceof ObjectReference) {
                ObjectReference object = (ObjectReference) ref;
                List<Field> fields = object.referenceType().allFields();
                for (int i=start; i<fields.size() && out.size()<count; i++)
                    out.add(variable(fields.get(i).name(), object.getValue(fields.get(i))));
            } else throw new IllegalArgumentException("Stale reference");
            return map("variables", out);
        }
        if (op.equals("setBreakpoints")) {
            vm.eventRequestManager().deleteEventRequests(new ArrayList<BreakpointRequest>(vm.eventRequestManager().breakpointRequests()));
            lines = lines(f[7]);
            for (ReferenceType type : vm.allClasses()) if (type.name().equals(main) || type.name().startsWith(main+"$")) install(type);
            List<Object> out = new ArrayList<>();
            for (int line : lines) {
                boolean verified = false;
                for (BreakpointRequest r : vm.eventRequestManager().breakpointRequests()) if (r.location().lineNumber() == line) verified = true;
                out.add(map("line", line, "verified", verified));
            }
            return map("breakpoints", out);
        }
        throw new IllegalArgumentException("Unsupported command");
    }

    private Object variable(String name, Value value) {
        int ref = 0;
        String text = String.valueOf(value);
        if (value instanceof StringReference) text = ((StringReference)value).value();
        else if (value instanceof ObjectReference) { ref = handle++; refs.put(ref, value); }
        if (text.length()>4096) text = text.substring(0,4096)+"…";
        return map("name", name, "value", text, "variablesReference", ref);
    }
    private static List<Integer> lines(String raw) {
        List<Integer> out = new ArrayList<>();
        if (!raw.isEmpty()) for (String one : raw.split(";")) out.add(Integer.parseInt(one));
        return out;
    }
    private static void output(InputStream stream, String category) {
        Thread t = new Thread(() -> {
            byte[] buf = new byte[4096]; int n;
            try {
                while ((n=stream.read(buf))>=0) send(map("event", "output", "body", map("category", category,
                        "output", new String(buf,0,n,StandardCharsets.UTF_8))));
            } catch (IOException ignored) { }
        });
        t.setDaemon(true); t.start();
    }
    private static Map<String,Object> map(Object... fields) {
        Map<String,Object> out = new LinkedHashMap<>();
        for (int i=0;i<fields.length;i+=2) out.put((String)fields[i],fields[i+1]);
        return out;
    }
    private static String json(Object value) {
        if (value == null) return "null";
        if (value instanceof Number || value instanceof Boolean) return value.toString();
        if (value instanceof Map) {
            List<String> fields = new ArrayList<>();
            for (Object key : ((Map<?,?>)value).keySet()) fields.add(json(key)+":"+json(((Map<?,?>)value).get(key)));
            return "{"+String.join(",",fields)+"}";
        }
        if (value instanceof Iterable) {
            List<String> fields = new ArrayList<>();
            for (Object v : (Iterable<?>)value) fields.add(json(v));
            return "["+String.join(",",fields)+"]";
        }
        StringBuilder b=new StringBuilder("\"");
        for (char c : value.toString().toCharArray()) {
            if (c=='"' || c=='\\') b.append('\\').append(c);
            else if (c<32) b.append(String.format("\\u%04x",(int)c));
            else b.append(c);
        }
        return b.append('"').toString();
    }
    private static synchronized void send(Object value) { System.out.println(json(value)); System.out.flush(); }
    public static void main(String[] args) throws Exception {
        DebugBridge bridge = new DebugBridge(args);
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        String line;
        while ((line=in.readLine())!=null) {
            String[] fields=line.split("\t",-1);
            int id=Integer.parseInt(fields[0]);
            try { send(map("id",id,"ok",true,"body",bridge.command(fields))); }
            catch (Exception error) { send(map("id",id,"ok",false)); }
        }
        bridge.vm.dispose();
    }
}
