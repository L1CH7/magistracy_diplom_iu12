#pragma once
#include <cstdint>
#include <iostream>
#include "common/graph_types.hpp"

namespace traffic {

/**
 * @brief Перегрузка оператора вывода для PQElement в пространстве имен traffic (для ADL).
 * @param os Поток вывода.
 * @param el Элемент приоритетной очереди.
 * @return Ссылка на поток вывода.
 */
inline std::ostream& operator<<(std::ostream& os, const PQElement& el) {
    os << "{" << el.weight << ", " << el.id << "}";
    return os;
}

} // namespace traffic

// Глобальные объявления Rust C FFI функций для работы с SimdQuickHeap
extern "C" {
    /**
     * @brief Создает новый экземпляр SimdQuickHeap в куче Rust.
     * @return Указатель на созданную очередь.
     */
    void * simd_quickheap_create();

    /**
     * @brief Уничтожает экземпляр SimdQuickHeap и освобождает память.
     * @param heap Указатель на очередь.
     */
    void simd_quickheap_destroy( void * heap );

    /**
     * @brief Вставляет элемент в очередь.
     * @param heap Указатель на очередь.
     * @param val Упакованный элемент (вес и ID вершины).
     */
    void simd_quickheap_push( void * heap, uint64_t val );

    /**
     * @brief Извлекает минимальный элемент из очереди.
     * @param heap Указатель на очередь.
     * @param out_val Указатель для записи извлеченного значения.
     * @return true, если элемент успешно извлечен, false если очередь пуста.
     */
    bool simd_quickheap_pop( void * heap, uint64_t * out_val );

    /**
     * @brief Очищает очередь.
     * @param heap Указатель на очередь.
     */
    void simd_quickheap_clear( void * heap );

    /**
     * @brief Возвращает текущее количество элементов в очереди.
     * @param heap Указатель на очередь.
     * @return Размер очереди.
     */
    size_t simd_quickheap_size( const void * heap );

    /**
     * @brief Проверяет, пуста ли очередь.
     * @param heap Указатель на очередь.
     * @return true, если очередь пуста, иначе false.
     */
    bool simd_quickheap_empty( const void * heap );
}

namespace traffic::router::compute {

/**
 * @brief Обертка над Rust-реализацией SimdQuickHeap (AVX2) для C++.
 * Использует C FFI для вызова быстрых SIMD-методов.
 */
class QuickHeapQueue
{
public:
    QuickHeapQueue()
    :   impl_( simd_quickheap_create() )
    {}

    ~QuickHeapQueue()
    {
        if( impl_ != nullptr )
        {
            simd_quickheap_destroy( impl_ );
        }
    }

    QuickHeapQueue( const QuickHeapQueue & ) = delete;
    QuickHeapQueue & operator=( const QuickHeapQueue & ) = delete;

    /**
     * @brief Резервирует место в очереди (no-op для SimdQuickHeap).
     */
    void reserve( size_t cap )
    {
        // no-op для Rust SimdQuickHeap
    }

    /**
     * @brief Полностью очищает очередь.
     */
    inline void clear() noexcept
    {
        if( impl_ != nullptr )
        {
            simd_quickheap_clear( impl_ );
        }
    }

    /**
     * @brief Добавляет элемент в приоритетную очередь.
     * @param el Элемент для вставки.
     */
    inline void push( traffic::PQElement el ) noexcept
    {
        if( impl_ != nullptr )
        {
            uint64_t val = ( static_cast< uint64_t >( el.weight ) << 32 ) | el.id;
            simd_quickheap_push( impl_, val );
        }
    }

    /**
     * @brief Извлекает минимальный элемент из очереди.
     * @return Минимальный элемент или пустой элемент, если очередь пуста.
     */
    inline traffic::PQElement pop() noexcept
    {
        if( impl_ != nullptr )
        {
            uint64_t val = 0;
            if( simd_quickheap_pop( impl_, &val ) )
            {
                traffic::PQElement el;
                el.weight = static_cast< traffic::PathWeight >( val >> 32 );
                el.id = static_cast< traffic::NodeID >( val & 0xFFFFFFFF );
                return el;
            }
        }
        return traffic::PQElement{};
    }

    /**
     * @brief Проверяет, пуста ли очередь.
     */
    [[nodiscard]] inline bool empty() const noexcept
    {
        return impl_ ? simd_quickheap_empty( impl_ ) : true;
    }

    /**
     * @brief Возвращает количество элементов в очереди.
     */
    [[nodiscard]] inline size_t size() const noexcept
    {
        return impl_ ? simd_quickheap_size( impl_ ) : 0;
    }

private:
    void * impl_; ///< Непрозрачный указатель на Rust-структуру SimdQuickHeap
};

} // namespace traffic::router::compute
