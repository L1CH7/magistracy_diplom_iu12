#pragma once

#include <string>
#include <sys/mman.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <stdexcept>
#include <system_error>

namespace traffic::common {

class MmapRegion {
public:
    explicit MmapRegion(const std::string& filepath) {
        fd_ = open(filepath.c_str(), O_RDONLY);
        if (fd_ == -1) {
            throw std::system_error(errno, std::generic_category(), "Failed to open " + filepath);
        }

        struct stat st;
        if (fstat(fd_, &st) == -1) {
            close(fd_);
            throw std::system_error(errno, std::generic_category(), "Failed to stat " + filepath);
        }
        size_ = st.st_size;

        if (size_ == 0) {
            close(fd_);
            ptr_ = nullptr;
            return;
        }

        ptr_ = mmap(nullptr, size_, PROT_READ, MAP_PRIVATE | MAP_POPULATE, fd_, 0);
        if (ptr_ == MAP_FAILED) {
            close(fd_);
            throw std::system_error(errno, std::generic_category(), "Failed to mmap " + filepath);
        }
        
        // Посказываем ядру, что будем читать линейно или случайно (в зависимости от использования)
        // Для CSR и Landmarks лучше MADV_WILLNEED
        madvise(ptr_, size_, MADV_WILLNEED);
    }

    ~MmapRegion() {
        if (ptr_ && ptr_ != MAP_FAILED) {
            munmap(ptr_, size_);
        }
        if (fd_ != -1) {
            close(fd_);
        }
    }

    // Disable copy
    MmapRegion(const MmapRegion&) = delete;
    MmapRegion& operator=(const MmapRegion&) = delete;

    // Enable move
    MmapRegion(MmapRegion&& other) noexcept 
        : ptr_(other.ptr_), size_(other.size_), fd_(other.fd_) {
        other.ptr_ = nullptr;
        other.size_ = 0;
        other.fd_ = -1;
    }

    [[nodiscard]] const void* data() const noexcept { return ptr_; }
    [[nodiscard]] size_t size() const noexcept { return size_; }
    [[nodiscard]] bool empty() const noexcept { return size_ == 0; }

private:
    void* ptr_ = nullptr;
    size_t size_ = 0;
    int fd_ = -1;
};

} // namespace traffic::common
