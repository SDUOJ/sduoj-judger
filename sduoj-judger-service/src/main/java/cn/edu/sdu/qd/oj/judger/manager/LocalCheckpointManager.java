package cn.edu.sdu.qd.oj.judger.manager;

import cn.edu.sdu.qd.oj.judger.config.PathConfig;
import com.google.common.collect.Sets;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.stereotype.Component;

import java.io.File;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;

@Slf4j
@Component
public class LocalCheckpointManager implements CommandLineRunner {

    private Set<String> checkpoints;

    @Override
    public void run(String... args) throws Exception {
        checkpoints= Optional.ofNullable(Paths.get(PathConfig.CURRENT_DIR, PathConfig.DATA_DIR).toString())
                .map(File::new)
                .map(File::list)
                .map(Arrays::stream)
                .map(o -> o.filter(s -> s.endsWith(".in") || s.endsWith(".out"))
                           .collect(Collectors.toSet()))
                .orElse(Sets.newHashSet());
        log.info("{}", checkpoints);
    }

    public boolean isCheckpointExist(Long checkpointId) {
        return checkpoints != null && checkpoints.contains(checkpointId.toString());
    }

    public void addCheckpoint(Long checkpointId) {
        Optional.ofNullable(checkpointId).map(Objects::toString).ifPresent(checkpoints::add);
    }

}
