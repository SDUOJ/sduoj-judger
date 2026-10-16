/*
 * Copyright 2020-2024 the original author or authors.
 *
 * Licensed under the Affero General Public License, Version 3.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.gnu.org/licenses/agpl-3.0.en.html
 */

package com.sduoj.judger.util;

import java.io.IOException;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.SecureDirectoryStream;
import java.nio.file.attribute.BasicFileAttributeView;

/** Delete through directory descriptors so program-created links cannot redirect cleanup. */
public final class WorkspaceFiles {
    private WorkspaceFiles() {}

    public static void delete(Path workspace) throws IOException {
        try (DirectoryStream<Path> parent = Files.newDirectoryStream(workspace.getParent())) {
            if (!(parent instanceof SecureDirectoryStream<?>)) {
                throw new IOException(
                        "Secure directory operations unavailable; workspace retained");
            }
            @SuppressWarnings("unchecked")
            SecureDirectoryStream<Path> secure = (SecureDirectoryStream<Path>) parent;
            delete(secure, workspace.getFileName());
        }
    }

    private static void delete(SecureDirectoryStream<Path> parent, Path name) throws IOException {
        try {
            var attributes =
                    parent.getFileAttributeView(
                                    name, BasicFileAttributeView.class, LinkOption.NOFOLLOW_LINKS)
                            .readAttributes();
            if (attributes.isDirectory()) {
                try (SecureDirectoryStream<Path> child =
                        parent.newDirectoryStream(name, LinkOption.NOFOLLOW_LINKS)) {
                    for (Path entry : child) {
                        delete(child, entry.getFileName());
                    }
                }
                parent.deleteDirectory(name);
            } else {
                parent.deleteFile(name);
            }
        } catch (NoSuchFileException alreadyRemoved) {
            // Concurrent normal cleanup may have finished this entry.
        }
    }
}
