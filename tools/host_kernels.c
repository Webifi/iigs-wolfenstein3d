/* Host build arithmetic. Keep Python's operation order and disable contraction. */
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

static double color_error(const double *t, const double *m,
                          double kc, double kh, double d0) {
    double dl = t[0] - m[0], dc = t[3] - m[3];
    double da = t[1] - m[1], db = t[2] - m[2];
    double l2 = dl * dl, c2 = dc * dc;
    double h2 = pow(da, 2.0) + pow(db, 2.0) - c2;
    if (h2 < 0.0) h2 = 0.0;
    double d = 100.0 * sqrt(l2 + kc * kc * c2 + kh * kh * h2);
    if (d0 != 0.0) d = d + d * d / d0;
    return d + t[5] * m[4];
}

void color_best(const double *targets, size_t count, const double *mixes,
                size_t mixed, size_t solid, double kc, double kh, double d0,
                double *values) {
    for (size_t i = 0; i < count; ++i) {
        const double *t = targets + 7 * i;
        size_t start = t[6] != 0.0 ? mixed : 0;
        size_t end = t[6] != 0.0 ? mixed + solid : mixed;
        double best = INFINITY;
        for (size_t j = start; j < end; ++j) {
            double v = color_error(t, mixes + 5 * j, kc, kh, d0);
            if (v < best) best = v;
        }
        values[i] = best;
    }
}

void color_costs(const double *targets, size_t count, const double *mixes,
                 size_t mixed, double kc, double kh, double d0, double *values) {
    for (size_t j=0; j<mixed; ++j)
        for (size_t i=0; i<count; ++i)
            values[j*count+i]=color_error(targets+7*i,mixes+5*j,kc,kh,d0);
}

void color_min(const double *targets, size_t count, const double **costs,
               size_t mixed, size_t solid, double *values) {
    for (size_t i=0; i<count; ++i) values[i]=INFINITY;
    /* Each target keeps the original mix order; scan contiguous cost rows. */
    for (size_t j=0; j<mixed+solid; ++j)
        for (size_t i=0; i<count; ++i)
            if ((targets[7*i+6]!=0.0)==(j>=mixed) && costs[j][i]<values[i])
                values[i]=costs[j][i];
}

size_t color_pick(const double *target, const double *mixes, size_t count,
                  double kc, double kh) {
    double best = INFINITY;
    size_t chosen = 0;
    for (size_t j = 0; j < count; ++j) {
        const double *m = mixes + 5*j;
        double dl = target[0]-m[0], dc = target[3]-m[3];
        /* The omitted hue term is nonnegative. These are the same rounded
           operations as color_error, so this lower bound preserves ties. */
        double lower = 100.0*sqrt(dl*dl + kc*kc*(dc*dc)) + target[5]*m[4];
        if (lower >= best) continue;
        double v = color_error(target, mixes + 5 * j, kc, kh, 0.0);
        if (v < best) { best = v; chosen = j; }
    }
    return chosen;
}

void color_bounds(const double *targets, size_t count, const double *mixes,
                  size_t mixed, double kc, double d0, double *columns) {
    for (size_t j=0; j<mixed; ++j) {
        const double *m=mixes+5*j;
        double *column=columns+(count+5)*j;
        memcpy(column,m,5*sizeof(double));
        for (size_t i=0; i<count; ++i) {
            const double *t=targets+7*i;
            double dl=t[0]-m[0],dc=t[3]-m[3];
            double d=100.0*sqrt(dl*dl+kc*kc*(dc*dc));
            if (d0!=0.0) d=d+d*d/d0;
            /* A negative sign marks a lower bound, including negative zero.
               Exact errors are nonnegative for the supported metrics. */
            column[5+i]=-(d+t[5]*m[4]);
        }
    }
}

void color_min_bounded(const double *targets, size_t count, double **columns,
                       size_t mixed, size_t solid, double kc, double kh,
                       double d0, const double *base, double *values) {
    for (size_t i=0; i<count; ++i) {
        const double *t=targets+7*i;
        size_t start=t[6]!=0.0 ? mixed : 0;
        size_t end=t[6]!=0.0 ? mixed+solid : mixed;
        double best=base ? base[i] : INFINITY;
        for (size_t j=start; j<end; ++j) {
            double *column=columns[j],value=column[5+i];
            if (signbit(value)) {
                if (-value>=best) continue;
                value=color_error(t,column,kc,kh,d0);
                column[5+i]=value;
            }
            if (value<best) best=value;
        }
        values[i]=best;
    }
}

static int floor_div(int a, int b) {
    int q = a / b;
    return q - (a % b < 0);
}

int sight_rows(const int *cells, size_t count, const int *bars, size_t bar_count,
               unsigned char *output) {
    size_t words = (count + 1 + 63) / 64;
    size_t stride = (count + 1 + 7) / 8;
    uint64_t *masks = calloc((count + 1) * words, sizeof(uint64_t));
    uint64_t *columns = calloc(64 * 65 * words, sizeof(uint64_t));
    uint64_t *forward = malloc((count + 1) * words * sizeof(uint64_t));
    if (!masks || !columns || !forward) {
        free(masks); free(columns); free(forward); return -1;
    }
    for (int swap = 0; swap < 2; ++swap) {
        int occupied[64] = {0};
        memset(columns, 0, 64 * 65 * words * sizeof(uint64_t));
        for (size_t i = 0; i < count; ++i) {
            int x = cells[2*i + swap], y = cells[2*i + 1-swap];
            size_t number = i + 1;
            columns[((size_t)x * 65 + y + 1) * words + number / 64] = UINT64_C(1) << (number % 64);
            occupied[x] = 1;
        }
        for (int x = 0; x < 64; ++x)
            for (int y = 1; y < 65; ++y)
                for (size_t w = 0; w < words; ++w)
                    columns[((size_t)x * 65 + y) * words + w] |= columns[((size_t)x * 65 + y - 1) * words + w];
        for (size_t bar = 0; bar < bar_count; ++bar) {
            const int *b = bars + 4 * bar;
            if (b[0] != swap) continue;
            int wall = b[1], lo = b[2], hi = b[3];
            for (size_t i = 0; i < count; ++i) {
                int ax = cells[2*i + swap], ay = cells[2*i + 1-swap];
                if (ax >= wall) continue;
                int near = (wall - ax) * 256 - 255, far = (wall + 1 - ax) * 256;
                int lower = lo * 256 + 128 - ay * 256;
                int upper = hi * 256 - 128 - ay * 256 - 255;
                uint64_t *row = masks + (i + 1) * words;
                for (int bx = wall + 1; bx < 64; ++bx) {
                    if (!occupied[bx]) continue;
                    int dx = bx - ax;
                    for (int side = 0; side < 2; ++side) {
                        int low_den = side ? near : far, high_den = side ? far : near;
                        int minimum = side ? 0 : -ay, maximum = side ? 63 - ay : -1;
                        int first = -floor_div(-lower * dx, low_den);
                        int last = floor_div(upper * dx - 1, high_den);
                        if (first < minimum) first = minimum;
                        if (last > maximum) last = maximum;
                        if (first > last) continue;
                        const uint64_t *a = columns + ((size_t)bx * 65 + ay + last + 1) * words;
                        const uint64_t *b = columns + ((size_t)bx * 65 + ay + first) * words;
                        for (size_t w = 0; w < words; ++w) row[w] |= a[w] ^ b[w];
                    }
                }
            }
        }
    }
    memcpy(forward, masks, (count + 1) * words * sizeof(uint64_t));
    for (size_t a = 0; a <= count; ++a) {
        for (size_t w = 0; w < words; ++w) {
            uint64_t bits = forward[a * words + w];
            while (bits) {
                unsigned bit = (unsigned)__builtin_ctzll(bits);
                size_t b = 64 * w + bit;
                masks[b * words + a / 64] |= UINT64_C(1) << (a % 64);
                bits &= bits - 1;
            }
        }
    }
    for (size_t i = 0; i <= count; ++i)
        for (size_t j = 0; j < stride; ++j)
            output[i * stride + j] = (unsigned char)(masks[i * words + j / 8] >> ((j % 8) * 8));
    free(masks); free(columns); free(forward);
    return 0;
}

/* HLZ's original candidate order and strict cost comparisons determine ties. */
typedef struct { int length, offset; } Match;
typedef struct { int *start; Match *matches; } Matches;

static int common(const unsigned char *data, int i, int j, int limit) {
    if (!memcmp(data+i, data+j, limit)) return limit;
    int lo=0, hi=limit, n=8;
    while (n<hi) {
        if (!memcmp(data+i, data+j, n)) { lo=n; n*=2; }
        else { hi=n; break; }
    }
    while (hi-lo>1) {
        int mid=(lo+hi)/2;
        if (!memcmp(data+i, data+j, mid)) lo=mid;
        else hi=mid;
    }
    return lo;
}

void hlz_free(Matches *m) {
    if (m) { free(m->start); free(m->matches); free(m); }
}

Matches *hlz_find(const unsigned char *data, int n, int chain, int nice) {
    Matches *m=calloc(1, sizeof(*m));
    int slots=1;
    while (slots<n*2) slots*=2;
    int *keys=calloc(slots, sizeof(int)), *heads=malloc(slots*sizeof(int));
    int *prev=malloc(n*sizeof(int));
    if (m) {
        m->start=calloc(n+1, sizeof(int));
        m->matches=malloc((size_t)n*(chain>0 ? chain : 1)*sizeof(Match));
    }
    if (!m || !m->start || !m->matches || !keys || !heads || !prev) {
        hlz_free(m); free(keys); free(heads); free(prev); return NULL;
    }
    int used=0;
    for (int i=0; i<n-2; ++i) {
        m->start[i]=used;
        int key=1+data[i]+(data[i+1]<<8)+(data[i+2]<<16);
        unsigned slot=((unsigned)key*2654435761u)&(slots-1);
        while (keys[slot] && keys[slot]!=key) slot=(slot+1)&(slots-1);
        int j=keys[slot] ? heads[slot] : -1;
        prev[i]=j; keys[slot]=key; heads[slot]=i;
        int limit=n-i<65535 ? n-i : 65535, best=2, left=chain;
        while (j>=0 && left) {
            --left;
            if (best<limit && data[j+best]==data[i+best]) {
                int length=common(data,i,j,limit);
                if (length>best) {
                    best=length;
                    m->matches[used++]=(Match){length,i-j};
                    if (length>=nice || length==limit) break;
                }
            }
            j=prev[j];
        }
    }
    for (int i=n-2; i<=n; ++i) m->start[i]=used;
    free(keys); free(heads); free(prev);
    return m;
}

int hlz_parse(const unsigned char *data, int n, const Matches *m,
              const double *lit, const double *off, int nice, int *tokens) {
    double *cost=malloc((n+1)*sizeof(double));
    int *lengths=calloc(n+1,sizeof(int)), *offsets=malloc((n+1)*sizeof(int));
    int *reps=malloc((n+1)*sizeof(int)), *repeat=malloc((n+1)*sizeof(int));
    if (!cost || !lengths || !offsets || !reps || !repeat) {
        free(cost); free(lengths); free(offsets); free(reps); free(repeat); return -1;
    }
    for (int i=0; i<=n; ++i) { cost[i]=INFINITY; reps[i]=1; }
    cost[0]=0.0;
    int i=0;
    while (i<n) {
        double c=cost[i];
        if (c==INFINITY) { ++i; continue; }
        int r=reps[i];
        double next=c+lit[data[i]];
        if (next<cost[i+1]) { cost[i+1]=next; lengths[i+1]=0; reps[i+1]=r; }
        int replen=0;
        if (r<=i && data[i]==data[i-r]) {
            replen=common(data,i,i-r,n-i<65535 ? n-i : 65535);
            if (replen>=2) {
                for (int len=replen>=nice ? replen : 2; len<=replen; ++len) {
                    double lc=len<35 ? lit[291+len-2] : len<291 ? lit[324]+8 : lit[325]+16;
                    next=c+lc;
                    if (next<cost[i+len]) {
                        cost[i+len]=next; lengths[i+len]=len; offsets[i+len]=r;
                        repeat[i+len]=1; reps[i+len]=r;
                    }
                }
            }
        }
        int longest=replen, lo=3;
        for (int k=m->start[i]; k<m->start[i+1]; ++k) {
            int len=m->matches[k].length, offset=m->matches[k].offset;
            if (offset==r) { lo=len+1; continue; }
            double oc=offset<=16 ? off[offset-1] : off[16+(offset>>8)]+8;
            double base=c+oc;
            for (int ln=len>=nice ? len : lo; ln<=len; ++ln) {
                double lc=ln<35 ? lit[257+ln-3] : ln<291 ? lit[289]+8 : lit[290]+16;
                next=base+lc;
                if (next<cost[i+ln]) {
                    cost[i+ln]=next; lengths[i+ln]=ln; offsets[i+ln]=offset;
                    repeat[i+ln]=0; reps[i+ln]=offset;
                }
            }
            lo=len+1;
            if (len>longest) longest=len;
        }
        i+=longest>=nice ? longest : 1;
    }
    int count=0;
    for (i=n; i>0; ) {
        int len=lengths[i];
        tokens[3*count]=len;
        tokens[3*count+1]=len ? offsets[i] : data[i-1];
        tokens[3*count+2]=len ? repeat[i] : 0;
        i-=len ? len : 1;
        ++count;
    }
    free(cost); free(lengths); free(offsets); free(reps); free(repeat);
    return count;
}

void audio_resample(const double *values, size_t n, double ratio, double cut,
                    int half, size_t count, int periodic, double pi, double *out) {
    for (size_t j=0; j<count; ++j) {
        double t=j/ratio, acc=0.0;
        int i0=(int)floor(t);
        for (int i=i0-half+1; i<i0+half+1; ++i) {
            double d=t-i;
            if (!periodic && (i<0 || (size_t)i>=n)) continue;
            double arg=d*cut;
            double s=arg==0.0 ? 1.0 : sin(pi*arg)/(pi*arg);
            double u=(d+half)/(2*half);
            if (u<0.0 || u>1.0) continue;
            double win=0.42-0.5*cos(2*pi*u)+0.08*cos(4*pi*u);
            double k=cut*s*win;
            int index=periodic ? ((i%(int)n)+(int)n)%(int)n : i;
            acc+=values[index]*k;
        }
        out[j]=acc;
    }
}

int dos_huffman(const unsigned char *stream, size_t n, const uint16_t *table,
                int size, unsigned char *out) {
    int node=254, used=0;
    for (size_t i=0; i<n; ++i) {
        for (int shift=0; shift<8; ++shift) {
            int value=table[2*node+((stream[i]>>shift)&1)];
            if (value<256) {
                if (used>=1048576) return -3;
                out[used++]=(unsigned char)value;
                node=254;
                if (used==size) return used;
            } else {
                node=value-256;
                if (node>=255) return -2;
            }
        }
    }
    return size>=0 ? -1 : used;
}

static int gamma_bits(unsigned n) {
    return 2*(32-__builtin_clz(n))-1;
}

int b1_parse(const unsigned char *data, int n, const int *choices, int *tokens) {
    int slots=1;
    while (slots<n*2) slots*=2;
    int *keys=calloc(slots,sizeof(int)), *heads=malloc(slots*sizeof(int));
    int *prev=malloc((n+1)*sizeof(int));
    double *lit=malloc((n+1)*sizeof(double)), *mat=malloc((n+1)*sizeof(double));
    int *loff=calloc(n+1,sizeof(int)), *moff=calloc(n+1,sizeof(int));
    int *lstart=calloc(n+1,sizeof(int)), *llen=calloc(n+1,sizeof(int));
    int *mlen=calloc(n+1,sizeof(int)), *state=calloc(n+1,sizeof(int));
    int *repeat=calloc(n+1,sizeof(int));
    if (!keys || !heads || !prev || !lit || !mat || !loff || !moff ||
        !lstart || !llen || !mlen || !state || !repeat) {
        n=-1; goto done;
    }
    for (int i=0; i<=n; ++i) lit[i]=mat[i]=INFINITY;
    mat[0]=0.0; moff[0]=1;
    for (int i=0; i<=n; ++i) {
        if (i>0 && lit[i-1]+8.1<lit[i]) {
            lit[i]=lit[i-1]+8.1; loff[i]=loff[i-1]; lstart[i]=-1;
        }
        if (mat[i]<INFINITY) {
            double base=mat[i]+1;
            for (int len=1; len<=64 && len<=n-i; ++len) {
                double c=base+gamma_bits(len)+8*len;
                if (c<lit[i+len]) {
                    lit[i+len]=c; loff[i+len]=moff[i]; lstart[i+len]=i; llen[i+len]=len;
                }
            }
        }
        if (i==n) break;
        Match candidates[68]; int count=0, limit=n-i<256 ? n-i : 256;
        if (i+2<n) {
            int key=1+data[i]+(data[i+1]<<8)+(data[i+2]<<16);
            unsigned slot=((unsigned)key*2654435761u)&(slots-1);
            while (keys[slot] && keys[slot]!=key) slot=(slot+1)&(slots-1);
            int j=keys[slot] ? heads[slot] : -1;
            prev[i]=j; keys[slot]=key; heads[slot]=i;
            int chain=0,best=0;
            while (j>=0 && i-j<=32768 && chain<64) {
                int len=common(data,i,j,limit);
                if (len>best) { best=len; candidates[count++]=(Match){len,i-j}; }
                if (best==limit) break;
                j=prev[j]; ++chain;
            }
        }
        for (int off=1; off<=4; ++off) {
            if (i-off>=0 && i+1<n && data[i-off]==data[i] && data[i-off+1]==data[i+1]) {
                int len=common(data,i,i-off,limit), duplicate=0;
                for (int j=0; j<count; ++j) if (candidates[j].offset==off) duplicate=1;
                if (len<3 || !duplicate) candidates[count++]=(Match){len,off};
            }
        }
        for (int j=0; j<count; ++j) {
            int longest=candidates[j].length, off=candidates[j].offset;
            const int *lengths=choices+longest*9;
            for (int st=0; st<2; ++st) {
                double src=st ? mat[i] : lit[i];
                int last=st ? moff[i] : loff[i];
                if (src==INFINITY) continue;
                for (int k=1; k<=lengths[0]; ++k) {
                    int len=lengths[k];
                    if (len>longest || len<2 || i+len>n) continue;
                    int rep=off==last && st==0;
                    int bits=rep ? gamma_bits(len) : gamma_bits((off-1)/128+1)+7+gamma_bits(len-1);
                    double c=(src+1)+bits;
                    if (c<mat[i+len]) {
                        mat[i+len]=c; moff[i+len]=off; mlen[i+len]=len;
                        state[i+len]=st; repeat[i+len]=rep;
                    }
                }
            }
        }
    }
    {
        int i=n, st=lit[n]<=mat[n] ? 0 : 1, count=0;
        while (i>0) {
            tokens[4*count]=st;
            if (st==0) {
                int run=0;
                while (lstart[i]==-1) { ++run; --i; }
                tokens[4*count+1]=lstart[i]; tokens[4*count+2]=llen[i]+run; tokens[4*count+3]=0;
                i=lstart[i]; st=1;
            } else {
                tokens[4*count+1]=mlen[i]; tokens[4*count+2]=moff[i]; tokens[4*count+3]=repeat[i];
                st=state[i]; i-=mlen[i];
            }
            ++count;
        }
        n=count;
    }
done:
    free(keys); free(heads); free(prev); free(lit); free(mat); free(loff); free(moff);
    free(lstart); free(llen); free(mlen); free(state); free(repeat);
    return n;
}

void nearest3(const double *points, size_t n, const double *centers, size_t k,
              int mode, double chroma, const double *biases, int *chosen, double *costs) {
    for (size_t i=0; i<n; ++i) {
        double best=INFINITY; int pick=0;
        for (size_t j=0; j<k; ++j) {
            double a=points[3*i]-centers[3*j];
            double b=points[3*i+1]-centers[3*j+1];
            double c=points[3*i+2]-centers[3*j+2];
            double d=mode==1 ? 3*a*a+4*b*b+2*c*c : mode==2 ?
                100*sqrt(pow(a,2.0)+chroma*chroma*(pow(b,2.0)+pow(c,2.0))) :
                pow(a,2.0)+pow(b,2.0)+pow(c,2.0);
            if (biases) d+=biases[j];
            if (d<best) { best=d; pick=(int)j; }
        }
        chosen[i]=pick; costs[i]=best;
    }
}

double color_score(const double *targets, size_t n, const double *costs, const double *base) {
    double result=0.0;
    for (size_t i=0; i<n; ++i) {
        double value=costs[i];
        if (base && !(value<base[i])) value=base[i];
        result += targets[7*i+4]*value;
    }
    return result;
}

static unsigned prefix_hash(const unsigned char *data, int n) {
    unsigned h=2166136261u;
    for (int i=0; i<n; ++i) h=(h^data[i])*16777619u;
    return h;
}

static int prefix_slot(const unsigned char *data, int at, int minimum,
                       const int *heads, int mask) {
    unsigned slot=prefix_hash(data+at,minimum)&mask;
    while (heads[slot] && memcmp(data+at,data+heads[slot]-1,minimum)) slot=(slot+1)&mask;
    return (int)slot;
}

int greedy_parse(const unsigned char *data, int n, int chain, int minimum,
                 int leave_last, int *tokens) {
    int slots=1;
    while (slots<n*2) slots*=2;
    int *heads=calloc(slots,sizeof(int)), *prev=malloc(n*sizeof(int));
    if (!heads || !prev) { free(heads); free(prev); return -1; }
    int anchor=0,i=0,count=0;
    while (i+minimum<=n-leave_last) {
        int slot=prefix_slot(data,i,minimum,heads,slots-1);
        int j=heads[slot]-1, best=0, offset=0, left=chain;
        int limit=n-i-leave_last;
        if (!leave_last && limit>32767) limit=32767;
        while (j>=0 && left) {
            --left;
            if (best<limit && data[j+best]==data[i+best]) {
                int length=common(data,i,j,limit);
                if (length>best) { best=length; offset=i-j; }
                if (best==limit) break;
            }
            j=prev[j];
        }
        int stop=i+1;
        if (best>=minimum) {
            tokens[4*count]=anchor; tokens[4*count+1]=i-anchor;
            tokens[4*count+2]=best; tokens[4*count+3]=offset; ++count;
            stop=i+best; anchor=stop;
        }
        for (int at=i; at<stop && at+minimum<=n; ++at) {
            int k=prefix_slot(data,at,minimum,heads,slots-1);
            prev[at]=heads[k]-1; heads[k]=at+1;
        }
        i=stop;
    }
    tokens[4*count]=anchor; tokens[4*count+1]=n-anchor;
    tokens[4*count+2]=tokens[4*count+3]=0; ++count;
    free(heads); free(prev);
    return count;
}

typedef struct { double real, imag; } HostComplex;
typedef HostComplex (*ComplexProduct)(HostComplex, HostComplex);

void audio_fft(HostComplex *a, size_t n, const HostComplex *twiddles, ComplexProduct product, int twiddle_first) {
    size_t j=0;
    for (size_t i=1; i<n; ++i) {
        size_t bit=n>>1;
        while (j&bit) { j^=bit; bit>>=1; }
        j|=bit;
        if (i<j) { HostComplex t=a[i]; a[i]=a[j]; a[j]=t; }
    }
    size_t at=0;
    for (size_t size=2; size<=n; size<<=1) {
        size_t half=size>>1;
        for (size_t s=0; s<n; s+=size) {
            for (size_t k=0; k<half; ++k) {
                HostComplex u=a[s+k], t=twiddle_first ? product(twiddles[at+k],a[s+k+half]) : product(a[s+k+half],twiddles[at+k]);
                a[s+k]=(HostComplex){u.real+t.real,u.imag+t.imag};
                a[s+k+half]=(HostComplex){u.real-t.real,u.imag-t.imag};
            }
        }
        at+=half;
    }
}

void effect_filter(const double *samples, size_t size, const double *kernel,
                   size_t count, double step, double half, int grid, double *out) {
    for (size_t k=0; k<count; ++k) {
        double c=(k+0.5)*step-0.5;
        int lo=(int)ceil(c-half), hi=(int)floor(c+half);
        if (lo<0) lo=0;
        if (hi>=(int)size) hi=(int)size-1;
        double acc=0.0;
        for (int j=lo; j<=hi; ++j) acc+=samples[j]*kernel[(int)(fabs(c-j)*grid+0.5)];
        out[k]=acc;
    }
}

void audio_correlation(const double *segment, size_t n, const double *loop,
                       size_t period, double *out) {
    for (size_t phase=0; phase<period; ++phase) {
        double score=0.0;
        for (size_t i=0; i<n; i+=2) score += segment[i]*loop[(phase+i)%period];
        out[phase]=score;
    }
}

void harmonic_sums(const double *samples, size_t n, const double *rotations,
                   size_t count, double *out, ComplexProduct product) {
    for (size_t h=0; h<count; ++h) {
        HostComplex rot={rotations[2*h], rotations[2*h+1]}, p={1.0,0.0};
        double ar=0.0, ai=0.0;
        for (size_t j=0; j<n; ++j) {
            /* Use this interpreter's exact complex rounding/overflow rules. */
            HostComplex term=product((HostComplex){samples[j],0.0},p);
            ar += term.real; ai += term.imag;
            p=product(p,rot);
        }
        out[2*h]=ar; out[2*h+1]=ai;
    }
}

int audio_pack(const unsigned char *data, int n, unsigned char *out) {
    int slots=1;
    while (slots<n*2) slots*=2;
    int *heads=calloc(slots,sizeof(int)), *prev=malloc((n+1)*sizeof(int));
    if (!heads || !prev) { free(heads); free(prev); return -1; }
    int at=0, used=0, literal=0, written=0;
    while (at<n) {
        int best=0, offset=0;
        if (at+3<=n) {
            int slot=prefix_slot(data,at,3,heads,slots-1), j=heads[slot]-1;
            int limit=n-at<130 ? n-at : 130;
            for (int chain=0; j>=0 && chain<64 && at-j<=65535; ++chain, j=prev[j]) {
                int size=common(data,at,j,limit);
                if (size>best) { best=size; offset=at-j; }
                if (size==limit) break;
            }
        }
        used=best>=4 ? best : 1;
        if (used>1) {
            if (literal) {
                out[written++]=literal-1;
                memcpy(out+written,data+at-literal,literal); written+=literal; literal=0;
            }
            out[written++]=128+used-3;
            out[written++]=offset&255; out[written++]=offset>>8;
        } else if (++literal==128) {
            out[written++]=127;
            memcpy(out+written,data+at-127,128); written+=128; literal=0;
        }
        for (int i=at; i<at+used && i+3<=n; ++i) {
            int slot=prefix_slot(data,i,3,heads,slots-1);
            prev[i]=heads[slot]-1; heads[slot]=i+1;
        }
        at+=used;
    }
    if (literal) {
        out[written++]=literal-1;
        memcpy(out+written,data+at-literal,literal); written+=literal;
    }
    free(heads); free(prev);
    return written;
}

/* Super Hi-Res page dither (tools/shr_search.py holds the Python twin; keep its order). */
static void shr_oklab(const double *rgb, double chroma, double *out) {
    double l = 0.4122214708 * rgb[0] + 0.5363325363 * rgb[1] + 0.0514459929 * rgb[2];
    double m = 0.2119034982 * rgb[0] + 0.6806995451 * rgb[1] + 0.1073969566 * rgb[2];
    double s = 0.0883024619 * rgb[0] + 0.2817188376 * rgb[1] + 0.6299787005 * rgb[2];
    l = pow(l, 1.0 / 3.0);
    m = pow(m, 1.0 / 3.0);
    s = pow(s, 1.0 / 3.0);
    out[0] = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s;
    out[1] = chroma * (1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s);
    out[2] = chroma * (0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s);
}

static double shr_d2(const double *a, const double *b) {
    double d0 = a[0] - b[0], d1 = a[1] - b[1], d2 = a[2] - b[2];
    return d0 * d0 + d1 * d1 + d2 * d2;
}

static int shr_rgb_dist(const unsigned char *a, const unsigned char *b) {
    int dr = (int)a[0] - (int)b[0], dg = (int)a[1] - (int)b[1], db = (int)a[2] - (int)b[2];
    return 3 * dr * dr + 4 * dg * dg + 2 * db * db;
}

static int shr_nearest(const double *colors, int count, const double *lab) {
    int best = 0;
    double bd = INFINITY;
    for (int j = 0; j < count; ++j) {
        double d = shr_d2(colors + 3 * j, lab);
        if (d < bd) { bd = d; best = j; }
    }
    return best;
}

static double shr_clip(double v) { return v < 0.0 ? 0.0 : (v > 1.0 ? 1.0 : v); }

/* Floyd-Steinberg; the row below gets half its share (ii-pix's decay). */
static void shr_spread(double *img, int h, int w, int y, int x, const double *err) {
    for (int c = 0; c < 3; ++c) {
        double e = err[c];
        double *p;
        if (x < w - 1) { p = img + ((size_t)y * w + x + 1) * 3 + c; *p = shr_clip(*p + e * (7.0 / 16.0)); }
        if (y < h - 1) {
            if (x > 0) { p = img + ((size_t)(y + 1) * w + x - 1) * 3 + c; *p = shr_clip(*p + 0.5 * e * (3.0 / 16.0)); }
            p = img + ((size_t)(y + 1) * w + x) * 3 + c; *p = shr_clip(*p + 0.5 * e * (5.0 / 16.0));
            if (x < w - 1) { p = img + ((size_t)(y + 1) * w + x + 1) * 3 + c; *p = shr_clip(*p + 0.5 * e * (1.0 / 16.0)); }
        }
    }
}

/* Dither to the 4096 IIgs colors. flags: 1 protected (nearest, no error), 2 flat. */
void shr_perfect(double *img, const double *src_snap, const unsigned char *src8, const unsigned char *flags,
                 int h, int w, const double *lab12, const double *snap12, const unsigned char *rgb12,
                 const double *lin12, double chroma, double amount, double snap, int *out) {
    double lab[3], err[3];
    for (int y = 0; y < h; ++y)
        for (int x = 0; x < w; ++x) {
            size_t i = (size_t)y * w + x;
            double *px = img + i * 3;
            if ((flags[i] & 1) || (snap > 0.0 && (flags[i] & 2))) {
                int word = shr_nearest(snap12, 4096, src_snap + i * 3);
                if ((flags[i] & 1) || shr_rgb_dist(src8 + i * 3, rgb12 + 3 * word) <= snap) {
                    out[i] = word;
                    continue;
                }
            }
            shr_oklab(px, chroma, lab);
            int word = shr_nearest(lab12, 4096, lab);
            out[i] = word;
            for (int c = 0; c < 3; ++c) {
                err[c] = (px[c] - lin12[3 * word + c]) * amount;
                px[c] = lin12[3 * word + c];
            }
            shr_spread(img, h, w, y, x, err);
        }
}

/* One dither pass with 16 palettes: each line takes the palette with the least weighted error for
   its current pixels (or keeps the line above's within keep), then error diffusion over at most top
   candidates near each source color. */
void shr_dither(double *img, const double *src_lab, const double *src_snap, const unsigned char *src8,
                const unsigned char *flags, const double *weight, int h, int w,
                const double *pal_lab, const double *pal_snap, const double *pal_lin, const unsigned char *pal8,
                double chroma, double amount, int top, double snap, double keep,
                int *out, int *line_pal, double *line_err, double *total_out) {
    double total = 0.0, lab[3], err[3];
    double *line = malloc((size_t)w * 3 * sizeof(double));
    for (int y = 0; y < h; ++y) {
        double cost[16];
        for (int x = 0; x < w; ++x) shr_oklab(img + ((size_t)y * w + x) * 3, chroma, line + 3 * x);
        for (int p = 0; p < 16; ++p) {
            double sum = 0.0;
            for (int x = 0; x < w; ++x) {
                double best = INFINITY;
                for (int j = 0; j < 16; ++j) {
                    double d = shr_d2(line + 3 * x, pal_lab + (p * 16 + j) * 3);
                    if (d < best) best = d;
                }
                sum += best * weight[(size_t)y * w + x];
            }
            cost[p] = sum;
        }
        int p = 0;
        for (int q = 1; q < 16; ++q) if (cost[q] < cost[p]) p = q;
        if (y > 0 && keep > 0.0 && cost[line_pal[y - 1]] <= cost[p] * (1.0 + keep)) p = line_pal[y - 1];
        line_pal[y] = p;
        line_err[y] = cost[p];
        const double *plab = pal_lab + p * 48, *psnap = pal_snap + p * 48, *plin = pal_lin + p * 48;
        const unsigned char *p8 = pal8 + p * 48;
        for (int x = 0; x < w; ++x) {
            size_t i = (size_t)y * w + x;
            double sd[16];
            int order[16];
            for (int j = 0; j < 16; ++j) {
                sd[j] = shr_d2(src_lab + i * 3, plab + 3 * j);
                int k = j;
                while (k > 0 && sd[order[k - 1]] > sd[j]) { order[k] = order[k - 1]; --k; }
                order[k] = j;
            }
            int near = order[0];
            int flat = snap > 0.0 && (flags[i] & 2);
            if (flat) near = shr_nearest(psnap, 16, src_snap + i * 3);
            if ((flags[i] & 1) || (flat && shr_rgb_dist(src8 + i * 3, p8 + 3 * near) <= snap)) {
                out[i] = near;
                total += sd[near] * weight[i];
                continue;
            }
            double *px = img + i * 3;
            shr_oklab(px, chroma, lab);
            double best = 1e9;
            int bi = near, count = top ? top : 16;
            for (int n = 0; n < count; ++n) {
                int j = top ? order[n] : n;
                double d = shr_d2(lab, plab + 3 * j);
                if (d < best) { best = d; bi = j; }
            }
            out[i] = bi;
            total += best * weight[i];
            for (int c = 0; c < 3; ++c) {
                err[c] = (px[c] - plin[3 * bi + c]) * amount;
                px[c] = plin[3 * bi + c];
            }
            shr_spread(img, h, w, y, x, err);
        }
    }
    free(line);
    *total_out = total;
}
