package cn.edu.sdu.qd.oj.judger.manager;

import cn.edu.sdu.qd.oj.judger.config.PathConfig;
import com.google.common.collect.Sets;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

import java.io.File;
import java.util.Arrays;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;

@Slf4j
@Component
public class LocalCheckpointManager implements CommandLineRunner {

    private final Set<String> checkpoints = Sets.newHashSet();

    @Override
    public void run(String... args) throws Exception {
        Set<String> checkpointFileNames = Optional.ofNullable(PathConfig.DATA_DIR)
                .map(File::new)
                .map(File::list)
                .map(Arrays::stream)
                .map(o -> o.filter(s -> s.endsWith(".in") || s.endsWith(".ans"))
                        .collect(Collectors.toSet()))
                .orElse(Sets.newHashSet());
        checkpointFileNames.forEach(o -> {
            if (o.endsWith(".in")) {
                String id = o.substring(0, o.length() - 3);
                if (checkpointFileNames.contains(id + ".ans")) {
                    checkpoints.add(id);
                }
            }
        });
        log.info("{}", checkpoints);
    }

    public boolean isCheckpointExist(Long checkpointId) {
        return checkpoints.contains(checkpointId.toString());
    }

    public void addCheckpoint(Long checkpointId) {
        synchronized (checkpoints) {
            Optional.ofNullable(checkpointId).map(Objects::toString).ifPresent(checkpoints::add);
        }
    }

}
